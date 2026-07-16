FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src
COPY . .
RUN dotnet restore src/Probora.Worker/Probora.Worker.csproj && \
    dotnet publish src/Probora.Worker/Probora.Worker.csproj -c Release --no-restore -o /app

FROM mcr.microsoft.com/dotnet/aspnet:10.0
WORKDIR /app
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgssapi-krb5-2 && \
    rm -rf /var/lib/apt/lists/*
COPY --from=build /app .
USER $APP_UID
ENTRYPOINT ["dotnet", "Probora.Worker.dll"]
