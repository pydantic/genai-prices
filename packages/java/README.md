# genai-prices for Java

A Java client for the genai-prices API at `https://genai-prices.pydantic.dev`. The API prices one LLM API call with the
same engine as the Python, JavaScript and Go packages. Unlike those packages, this client sends each call to the API.

The build generates the client from [`openapi.json`](openapi.json) with OpenAPI Generator. Only `GenaiPrices` is
written by hand.

```java
import dev.pydantic.genaiprices.GenaiPrices;
import dev.pydantic.genaiprices.model.PriceRequest;
import dev.pydantic.genaiprices.model.PriceResponse;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.Map;

public class Example {
    public static void main(String[] args) throws Exception {
        PriceResponse price = GenaiPrices.client().price(new PriceRequest()
                .model("gpt-4o")
                .providerId("openai")
                .timestamp(OffsetDateTime.parse("2025-01-01T00:00:00Z"))
                .usage(Map.of("input_tokens", new BigDecimal(1000), "output_tokens", new BigDecimal(300))));

        BigDecimal total = new BigDecimal(price.getTotalPrice());
        System.out.println(total); // 0.0055
    }
}
```

The prices are decimal strings. Parse them with `new BigDecimal(...)`, so no float rounding occurs.

## Price a raw provider response

Send the response body that the provider returned in place of `usage`. The API extracts the usage and the model, and
returns the usage it extracted.

```java
Map<String, Object> openaiResponse = Map.of(
        "model", "gpt-4o",
        "usage", Map.of("prompt_tokens", 1000, "completion_tokens", 300));

PriceResponse price = GenaiPrices.client()
        .price(new PriceRequest().providerId("openai").apiFlavor("chat").response(openaiResponse));
```

## Errors

A failed call raises `ApiException`. `getCode()` is the HTTP status, and `getResponseBody()` is an RFC 9457 problem
detail whose `detail` names the cause.

| Status | Cause                                                        |
| ------ | ------------------------------------------------------------ |
| `404`  | No provider or model matches.                                |
| `422`  | The request is not valid, or the API cannot price the usage. |

> [!NOTE]
> Use `GenaiPrices.client()`, not `new DefaultApi()`. It sets the `User-Agent` to `genai-prices-java/<version>`,
> which the API uses to count requests per client. The generated client cannot set this header.

## Develop

Requires Java 11 or later to use, and a JDK with Maven to build.

```bash
make test-java
```

The API owns the document. To pick up a change to the API, refresh `openapi.json` and commit it:

```bash
make java-openapi
```
