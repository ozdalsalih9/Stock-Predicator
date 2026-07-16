using System.Security.Cryptography;

namespace Probora.Api.Middleware;

public sealed class ETagMiddleware(RequestDelegate next)
{
    public async Task InvokeAsync(HttpContext context)
    {
        if (!HttpMethods.IsGet(context.Request.Method) ||
            context.Request.Path.StartsWithSegments("/hubs") ||
            context.Request.Path.StartsWithSegments("/health"))
        {
            await next(context);
            return;
        }

        Stream original = context.Response.Body;
        await using MemoryStream buffer = new();
        context.Response.Body = buffer;
        await next(context);

        if (context.Response.StatusCode == StatusCodes.Status200OK && buffer.Length > 0)
        {
            byte[] hash = SHA256.HashData(buffer.ToArray());
            string etag = $"\"{Convert.ToHexString(hash)}\"";
            context.Response.Headers.ETag = etag;
            context.Response.Headers.CacheControl = "public,max-age=15,must-revalidate";
            if (context.Request.Headers.IfNoneMatch.Any(value => value == etag))
            {
                context.Response.StatusCode = StatusCodes.Status304NotModified;
                context.Response.ContentLength = 0;
                context.Response.Body = original;
                return;
            }
        }

        buffer.Position = 0;
        context.Response.Body = original;
        await buffer.CopyToAsync(original, context.RequestAborted);
    }
}
