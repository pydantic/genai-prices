# genai-prices for Kotlin

A Kotlin Multiplatform client for the genai-prices API at `https://genai-prices.pydantic.dev`. It runs on the JVM,
Android and iOS. The API prices one LLM API call with the same engine as the Python, JavaScript and Go packages. Unlike
those packages, this client sends each call to the API.

The build generates the client from [`openapi.json`](openapi.json) with OpenAPI Generator's `kotlin` generator and its
`multiplatform` library (Ktor and kotlinx.serialization). Only `GenaiPrices` is written by hand.

```kotlin
import dev.pydantic.genaiprices.GenaiPrices
import dev.pydantic.genaiprices.models.PriceRequest
import kotlin.time.Instant

suspend fun main() {
    val response = GenaiPrices.client().price(
        PriceRequest(
            model = "gpt-4o",
            providerId = "openai",
            timestamp = Instant.parse("2025-01-01T00:00:00Z"),
            usage = mapOf("input_tokens" to 1000.0, "output_tokens" to 300.0),
        ),
    )
    println(response.body().totalPrice) // 0.0055
}
```

The prices are decimal strings, so no float rounding occurs. On the JVM, parse them with `BigDecimal(totalPrice)`.

## Price a raw provider response

Send the response body that the provider returned in place of `usage`. The API extracts the usage and the model, and
returns the usage it extracted.

```kotlin
val openaiResponse = buildJsonObject {
    put("model", "gpt-4o")
    putJsonObject("usage") {
        put("prompt_tokens", 1000)
        put("completion_tokens", 300)
    }
}

val response = GenaiPrices.client()
    .price(PriceRequest(providerId = "openai", apiFlavor = "chat", response = openaiResponse))
```

## Errors

`price` does not throw for an HTTP error. Check `response.success` and `response.status` before you call `body()`.
An error body is an RFC 9457 problem detail whose `detail` names the cause.

| Status | Cause                                                        |
| ------ | ------------------------------------------------------------ |
| `404`  | No provider or model matches.                                |
| `422`  | The request is not valid, or the API cannot price the usage. |

> [!NOTE]
> Use `GenaiPrices.client()`, not `DefaultApi()`. It sets the `User-Agent` to `genai-prices-kotlin/<version>`, which
> the API uses to count requests per client.

## Engines

`GenaiPrices.client()` uses the CIO engine on the JVM and Android, and the Darwin engine on iOS. To use your own engine,
or `MockEngine` in tests, pass it as `engine`.

## Develop

Requires a JDK and Gradle 8.14. The build compiles the iOS targets on Linux as well, through Kotlin/Native klib
cross-compilation. Running the iOS tests needs macOS.

```bash
make test-kotlin
```

The API owns the document. To pick up a change to the API, refresh `openapi.json` and commit it:

```bash
make kotlin-openapi
```
