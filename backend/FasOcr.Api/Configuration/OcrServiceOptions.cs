namespace FasOcr.Api.Configuration;

public sealed class OcrServiceOptions
{
    public string BaseUrl { get; set; } = "http://127.0.0.1:8000";
    public int TimeoutSeconds { get; set; } = 180;
    public long MaxUploadBytes { get; set; } = 25_000_000;
}
