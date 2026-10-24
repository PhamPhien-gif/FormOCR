using System.Net.Http.Headers;
using System.Text.Json;
using FasOcr.Api.Contracts;

namespace FasOcr.Api.Services;

public sealed class OcrServiceClient(HttpClient httpClient) : IOcrServiceClient
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);

    public async Task<OcrResponse> ExtractAsync(IReadOnlyList<IFormFile> files, string? formType,
        string? formVersion, CancellationToken cancellationToken)
    {
        using var multipart = new MultipartFormDataContent();
        foreach (var file in files)
        {
            var content = new StreamContent(file.OpenReadStream());
            content.Headers.ContentType = new MediaTypeHeaderValue(UploadValidator.ContentTypeFor(file));
            multipart.Add(content, "file", Path.GetFileName(file.FileName));
        }
        if (!string.IsNullOrWhiteSpace(formType))
            multipart.Add(new StringContent(formType), "form_type");
        if (!string.IsNullOrWhiteSpace(formVersion))
            multipart.Add(new StringContent(formVersion), "form_version");
        using var request = new HttpRequestMessage(HttpMethod.Post, "/api/v1/ocr/extract") { Content = multipart };
        using var response = await SendAsync(request, cancellationToken);
        var result = await DeserializeAsync<OcrResponse>(response, cancellationToken);
        if (result is null || !result.IsValid())
            throw new OcrUpstreamException(502, "INVALID_OCR_RESPONSE", "OCR service returned an invalid response.");
        return result;
    }

    public async Task<FormDefinitionResponse> GetFormAsync(CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, "/api/v1/forms/current");
        using var response = await SendAsync(request, cancellationToken);
        var result = await DeserializeAsync<FormDefinitionResponse>(response, cancellationToken);
        if (result is null || !result.IsValid())
            throw new OcrUpstreamException(502, "INVALID_OCR_RESPONSE", "OCR service returned an invalid form definition.");
        return result;
    }

    private async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        try
        {
            var response = await httpClient.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
            if (response.IsSuccessStatusCode)
                return response;
            ApiError? upstreamError = null;
            try
            {
                await using var body = await response.Content.ReadAsStreamAsync(cancellationToken);
                upstreamError = await JsonSerializer.DeserializeAsync<ApiError>(body, JsonOptions, cancellationToken);
            }
            catch (JsonException) { /* Upstream error bodies may be plain text. */ }
            var status = (int)response.StatusCode;
            response.Dispose();
            if (status is 400 or 413 or 415 or 422)
                throw new OcrUpstreamException(status, upstreamError?.Code ?? "INVALID_DOCUMENT", upstreamError?.Message ?? "The uploaded form is invalid.");
            throw new OcrUpstreamException(status == 504 ? 504 : 503,
                status == 504 ? "OCR_TIMEOUT" : "OCR_SERVICE_UNAVAILABLE",
                status == 504 ? "OCR service timed out." : "OCR service is temporarily unavailable.");
        }
        catch (HttpRequestException)
        {
            throw new OcrUpstreamException(503, "OCR_SERVICE_UNAVAILABLE", "OCR service is temporarily unavailable.");
        }
        catch (TaskCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            throw new OcrUpstreamException(504, "OCR_TIMEOUT", "OCR service timed out.");
        }
    }

    private static async Task<T?> DeserializeAsync<T>(HttpResponseMessage response, CancellationToken cancellationToken)
    {
        try
        {
            await using var body = await response.Content.ReadAsStreamAsync(cancellationToken);
            return await JsonSerializer.DeserializeAsync<T>(body, JsonOptions, cancellationToken);
        }
        catch (JsonException)
        {
            throw new OcrUpstreamException(502, "INVALID_OCR_RESPONSE", "OCR service returned malformed JSON.");
        }
    }
}
