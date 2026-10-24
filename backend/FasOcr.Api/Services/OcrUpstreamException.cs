namespace FasOcr.Api.Services;

public sealed class OcrUpstreamException(int statusCode, string code, string message) : Exception(message)
{
    public int StatusCode { get; } = statusCode;
    public string Code { get; } = code;
}
