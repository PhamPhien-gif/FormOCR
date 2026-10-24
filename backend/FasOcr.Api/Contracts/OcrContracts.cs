using System.Text.Json;
using System.Text.Json.Serialization;

namespace FasOcr.Api.Contracts;

public sealed class ApiError
{
    public string Code { get; set; } = "UNKNOWN_ERROR";
    public string Message { get; set; } = "The request could not be completed.";
}

public sealed class OcrIssue
{
    public string Code { get; set; } = "";
    public string Message { get; set; } = "";
    public string Severity { get; set; } = "WARNING";
    public string? Field { get; set; }
}

public sealed class OcrEvidence
{
    [JsonPropertyName("bounding_box")]
    public int[]? BoundingBox { get; set; }
    [JsonPropertyName("coordinate_system")]
    public string? CoordinateSystem { get; set; }
}

public sealed class OcrField
{
    public string? Value { get; set; }
    public string? RawValue { get; set; }
    public string Status { get; set; } = "";
    public OcrEvidence? Evidence { get; set; }
    public List<OcrIssue> Issues { get; set; } = [];

    [JsonExtensionData]
    public Dictionary<string, JsonElement>? Extra { get; set; }
}

public sealed class OcrResponse
{
    public string RequestId { get; set; } = "";
    public string SchemaVersion { get; set; } = "";
    public string Status { get; set; } = "";
    public string FormType { get; set; } = "";
    public string FormVersion { get; set; } = "";
    public int PageCount { get; set; }
    public List<int> ProcessedPages { get; set; } = [];
    public bool TemplateMatch { get; set; }
    public string OcrModel { get; set; } = "";
    public double ProcessingSeconds { get; set; }
    public double OcrSeconds { get; set; }
    public Dictionary<string, OcrField> Fields { get; set; } = [];
    public List<OcrIssue> Issues { get; set; } = [];
    public JsonElement ImageQuality { get; set; }
    public JsonElement FormValidation { get; set; }
    public JsonElement Validation { get; set; }
    public bool CanReview { get; set; }
    public bool RequiresRecapture { get; set; }
    public bool RequiresNewForm { get; set; }
    public Dictionary<string, List<string>> Transcripts { get; set; } = [];

    [JsonExtensionData]
    public Dictionary<string, JsonElement>? Extra { get; set; }

    public bool IsValid() =>
        !string.IsNullOrWhiteSpace(RequestId) &&
        !string.IsNullOrWhiteSpace(FormType) &&
        !string.IsNullOrWhiteSpace(FormVersion) &&
        Status is "REVIEW_REQUIRED" or "RECAPTURE_REQUIRED" or "COMPLETED" or "FAILED" &&
        Fields is not null &&
        Fields.Values.All(field => field.Status is "EXTRACTED" or "EMPTY" or "UNREADABLE" or "NOT_VISIBLE" or "AMBIGUOUS");
}

public sealed class FormFieldDefinition
{
    public string Id { get; set; } = "";
    public string Label { get; set; } = "";
    public int Page { get; set; }
    public string Section { get; set; } = "";
    public string DataType { get; set; } = "string";
    public bool Required { get; set; }
}

public sealed class FormDefinitionResponse
{
    public string FormType { get; set; } = "";
    public string FormVersion { get; set; } = "";
    public int PageCount { get; set; }
    public List<FormFieldDefinition> Fields { get; set; } = [];

    public bool IsValid() =>
        !string.IsNullOrWhiteSpace(FormType) &&
        !string.IsNullOrWhiteSpace(FormVersion) &&
        Fields.Count > 0 &&
        Fields.All(field => !string.IsNullOrWhiteSpace(field.Id) && !string.IsNullOrWhiteSpace(field.Label) && field.Page > 0) &&
        Fields.Select(field => field.Id).Distinct().Count() == Fields.Count;
}
