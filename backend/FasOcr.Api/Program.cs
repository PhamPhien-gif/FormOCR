using FasOcr.Api.Configuration;
using FasOcr.Api.Contracts;
using FasOcr.Api.Services;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.Extensions.Options;

var builder = WebApplication.CreateBuilder(args);
var configured = builder.Configuration.GetSection("OcrService").Get<OcrServiceOptions>() ?? new();
builder.WebHost.ConfigureKestrel(options => options.Limits.MaxRequestBodySize = configured.MaxUploadBytes + 1024 * 1024);
builder.Services.Configure<FormOptions>(options =>
{
    options.MultipartBodyLengthLimit = configured.MaxUploadBytes + 1024 * 1024;
    options.MemoryBufferThreshold = (int)Math.Min(configured.MaxUploadBytes, int.MaxValue);
});
builder.Services.Configure<OcrServiceOptions>(builder.Configuration.GetSection("OcrService"));
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();
builder.Services.AddHttpClient<IOcrServiceClient, OcrServiceClient>((provider, client) =>
{
    var options = provider.GetRequiredService<IOptions<OcrServiceOptions>>().Value;
    client.BaseAddress = new Uri(options.BaseUrl);
    client.Timeout = TimeSpan.FromSeconds(options.TimeoutSeconds);
});
var allowedOrigins = builder.Configuration.GetSection("Frontend:AllowedOrigins").Get<string[]>()
    ?? ["http://localhost:5173"];
builder.Services.AddCors(options => options.AddPolicy("frontend", policy =>
    policy.WithOrigins(allowedOrigins).AllowAnyHeader().AllowAnyMethod()));

var app = builder.Build();
app.UseCors("frontend");
app.UseSwagger();
app.UseSwaggerUI(options => options.SwaggerEndpoint("/swagger/v1/swagger.json", "FAS OCR API v1"));

app.MapGet("/health", () => Results.Ok(new { status = "healthy", service = "fas-ocr-api" }))
    .WithTags("Health")
    .WithSummary("Check gateway health");

app.MapGet("/api/v1/fas/form", async (IOcrServiceClient client, CancellationToken cancellationToken) =>
{
    try { return Results.Json(await client.GetFormAsync(cancellationToken)); }
    catch (OcrUpstreamException exc) { return Error(exc); }
}).WithTags("FAS OCR")
  .WithSummary("Get the current FAS form schema")
  .Produces<FormDefinitionResponse>(StatusCodes.Status200OK)
  .Produces<ApiError>(StatusCodes.Status503ServiceUnavailable);

app.MapPost("/api/v1/fas/ocr", async (HttpRequest request, IOcrServiceClient client,
    IOptions<OcrServiceOptions> options, CancellationToken cancellationToken) =>
{
    if (!request.HasFormContentType)
        return Error(new OcrUpstreamException(415, "UNSUPPORTED_FORMAT", "Send multipart form data with a file field."));
    try
    {
        var form = await request.ReadFormAsync(cancellationToken);
        var files = form.Files.GetFiles("file");
        var invalid = await UploadValidator.ValidateAsync(files, options.Value, cancellationToken);
        if (invalid is not null) return Error(invalid);
        var result = await client.ExtractAsync(files, form["form_type"], form["form_version"], cancellationToken);
        return Results.Json(result);
    }
    catch (BadHttpRequestException)
    {
        return Error(new OcrUpstreamException(413, "FILE_TOO_LARGE", "The upload exceeds the configured size limit."));
    }
    catch (InvalidDataException)
    {
        return Error(new OcrUpstreamException(400, "INVALID_MULTIPART", "The multipart upload could not be read."));
    }
    catch (OcrUpstreamException exc) { return Error(exc); }
}).DisableAntiforgery()
  .WithTags("FAS OCR")
  .WithSummary("Extract fields from one PDF or three page images")
  .WithDescription("Send one PDF or three PNG/JPEG images in page order using repeated 'file' multipart fields. The optional form_type and form_version must match the current form.")
  .Accepts<OcrUploadRequest>("multipart/form-data")
  .Produces<OcrResponse>(StatusCodes.Status200OK)
  .Produces<ApiError>(StatusCodes.Status400BadRequest)
  .Produces<ApiError>(StatusCodes.Status413PayloadTooLarge)
  .Produces<ApiError>(StatusCodes.Status415UnsupportedMediaType)
  .Produces<ApiError>(StatusCodes.Status422UnprocessableEntity)
  .Produces<ApiError>(StatusCodes.Status502BadGateway)
  .Produces<ApiError>(StatusCodes.Status503ServiceUnavailable)
  .Produces<ApiError>(StatusCodes.Status504GatewayTimeout);

app.Run();

static IResult Error(OcrUpstreamException exc) => Results.Json(
    new ApiError { Code = exc.Code, Message = exc.Message }, statusCode: exc.StatusCode);

public partial class Program { }
