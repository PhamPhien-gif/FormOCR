using FasOcr.Api.Contracts;

namespace FasOcr.Api.Services;

public interface IOcrServiceClient
{
    Task<OcrResponse> ExtractAsync(IReadOnlyList<IFormFile> files, string? formType,
        string? formVersion, CancellationToken cancellationToken);

    Task<FormDefinitionResponse> GetFormAsync(CancellationToken cancellationToken);
}
