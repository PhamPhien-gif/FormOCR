using System.Net;
using System.Text;
using FasOcr.Api.Configuration;
using FasOcr.Api.Services;
using Microsoft.AspNetCore.Http;

var pdf = File("form.pdf", "%PDF- test");
var options = new OcrServiceOptions { MaxUploadBytes = 100 };
Check((await UploadValidator.ValidateAsync([], options, default))?.Code == "INVALID_PAGE_COUNT", "missing file");
Check((await UploadValidator.ValidateAsync([File("form.pdf", "invalid")], options, default))?.Code == "UNSUPPORTED_FORMAT", "invalid signature");
Check((await UploadValidator.ValidateAsync([pdf], options, default)) is null, "valid PDF upload");

var forwarded = false;
var goodJson = """
{"requestId":"r1","schemaVersion":"2.0","status":"REVIEW_REQUIRED","formType":"MOE_FAS","formVersion":"2026-10","pageCount":5,"processedPages":[1,2,3],"templateMatch":true,"ocrModel":"RapidOCR","processingSeconds":1.0,"ocrSeconds":0.5,"fields":{"applicant_name":{"value":"Ethan","rawValue":"Ethan","status":"EXTRACTED","issues":[],"evidence":{"bounding_box":[1,2,3,4],"coordinate_system":"reference_pixels"}}},"issues":[],"imageQuality":{},"formValidation":{},"validation":{},"canReview":true,"requiresRecapture":false,"requiresNewForm":false,"transcripts":{}}
""";
var client = Client(async request =>
{
    forwarded = request.Method == HttpMethod.Post && request.RequestUri?.AbsolutePath == "/api/v1/ocr/extract"
        && request.Content?.Headers.ContentType?.MediaType == "multipart/form-data"
        && (await request.Content.ReadAsStringAsync()).Contains("form.pdf");
    return Json(HttpStatusCode.OK, goodJson);
});
var extracted = await client.ExtractAsync([pdf], "MOE_FAS", "2026-10", default);
Check(forwarded, "multipart forwarding");
Check(extracted.Fields["applicant_name"].Value == "Ethan", "OCR response deserialization");
Check(extracted.Fields["applicant_name"].Evidence?.BoundingBox?.SequenceEqual([1, 2, 3, 4]) == true,
    "field evidence preserved");

await ExpectError("OCR_SERVICE_UNAVAILABLE", 503, () =>
    Client(_ => throw new HttpRequestException()).GetFormAsync(default));
await ExpectError("OCR_TIMEOUT", 504, () =>
    Client(_ => throw new TaskCanceledException()).GetFormAsync(default));
await ExpectError("INVALID_OCR_RESPONSE", 502, () =>
    Client(_ => Task.FromResult(Json(HttpStatusCode.OK, "not json"))).GetFormAsync(default));
await ExpectError("INVALID_DOCUMENT", 422, () =>
    Client(_ => Task.FromResult(Json(HttpStatusCode.UnprocessableEntity,
        "{\"code\":\"INVALID_DOCUMENT\",\"message\":\"Wrong form\"}"))).GetFormAsync(default));

Console.WriteLine("Gateway contract tests passed (8 checks).");

static IFormFile File(string name, string contents)
{
    var bytes = Encoding.UTF8.GetBytes(contents);
    return new FormFile(new MemoryStream(bytes), 0, bytes.Length, "file", name)
    { Headers = new HeaderDictionary(), ContentType = "application/pdf" };
}

static OcrServiceClient Client(Func<HttpRequestMessage, Task<HttpResponseMessage>> responder)
{
    var http = new HttpClient(new FakeHandler(responder)) { BaseAddress = new Uri("http://localhost:8000"), Timeout = TimeSpan.FromSeconds(2) };
    return new OcrServiceClient(http);
}

static HttpResponseMessage Json(HttpStatusCode status, string body) => new(status)
{ Content = new StringContent(body, Encoding.UTF8, "application/json") };

static async Task ExpectError(string code, int status, Func<Task> action)
{
    try { await action(); throw new Exception($"Expected {code}"); }
    catch (OcrUpstreamException error) { Check(error.Code == code && error.StatusCode == status, code); }
}

static void Check(bool success, string label)
{
    if (!success) throw new Exception($"Failed: {label}");
}

sealed class FakeHandler(Func<HttpRequestMessage, Task<HttpResponseMessage>> responder) : HttpMessageHandler
{
    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => responder(request);
}
