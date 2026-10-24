using FasOcr.Api.Configuration;

namespace FasOcr.Api.Services;

public static class UploadValidator
{
    private static readonly Dictionary<string, (byte[] Signature, string ContentType)> Formats = new(StringComparer.OrdinalIgnoreCase)
    {
        [".pdf"] = ("%PDF-"u8.ToArray(), "application/pdf"),
        [".png"] = ([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A], "image/png"),
        [".jpg"] = ([0xFF, 0xD8, 0xFF], "image/jpeg"),
        [".jpeg"] = ([0xFF, 0xD8, 0xFF], "image/jpeg")
    };

    public static async Task<OcrUpstreamException?> ValidateAsync(IReadOnlyList<IFormFile> files,
        OcrServiceOptions options, CancellationToken cancellationToken)
    {
        if (files.Count is not (1 or 3))
            return new OcrUpstreamException(422, "INVALID_PAGE_COUNT", "Provide one PDF or three page images in order.");
        if (files.Sum(file => file.Length) > options.MaxUploadBytes)
            return new OcrUpstreamException(413, "FILE_TOO_LARGE", "Uploaded files exceed the configured size limit.");
        foreach (var file in files)
        {
            if (file.Length == 0)
                return new OcrUpstreamException(400, "EMPTY_FILE", "The uploaded file is empty.");
            var extension = Path.GetExtension(file.FileName);
            if (!Formats.TryGetValue(extension, out var format))
                return new OcrUpstreamException(415, "UNSUPPORTED_FORMAT", "Only PDF, PNG and JPEG files are supported.");
            await using var stream = file.OpenReadStream();
            var prefix = new byte[format.Signature.Length];
            var count = 0;
            while (count < prefix.Length)
            {
                var read = await stream.ReadAsync(prefix.AsMemory(count), cancellationToken);
                if (read == 0) break;
                count += read;
            }
            if (count != prefix.Length || !prefix.AsSpan().SequenceEqual(format.Signature))
                return new OcrUpstreamException(415, "UNSUPPORTED_FORMAT", $"{Path.GetFileName(file.FileName)} does not match its file extension.");
        }
        var pdfCount = files.Count(file => Path.GetExtension(file.FileName).Equals(".pdf", StringComparison.OrdinalIgnoreCase));
        if ((files.Count == 1 && pdfCount != 1) || (files.Count == 3 && pdfCount != 0))
            return new OcrUpstreamException(422, "INVALID_PAGE_COUNT", "Provide one PDF or three page images in order.");
        return null;
    }

    public static string ContentTypeFor(IFormFile file) =>
        Formats[Path.GetExtension(file.FileName)].ContentType;
}
