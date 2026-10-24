using System.ComponentModel.DataAnnotations;
using System.Text.Json.Serialization;

namespace FasOcr.Api.Contracts;

/// <summary>Swagger schema for the multipart body read and validated by the OCR endpoint.</summary>
public sealed class OcrUploadRequest
{
    [JsonPropertyName("file")]
    [Required]
    public IReadOnlyList<IFormFile> File { get; set; } = [];

    [JsonPropertyName("form_type")]
    public string? FormType { get; set; }

    [JsonPropertyName("form_version")]
    public string? FormVersion { get; set; }
}
