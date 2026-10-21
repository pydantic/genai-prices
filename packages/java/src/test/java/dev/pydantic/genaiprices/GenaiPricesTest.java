package dev.pydantic.genaiprices;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.sun.net.httpserver.HttpServer;
import dev.pydantic.genaiprices.api.DefaultApi;
import dev.pydantic.genaiprices.client.ApiException;
import dev.pydantic.genaiprices.model.PriceRequest;
import dev.pydantic.genaiprices.model.PriceResponse;
import java.io.IOException;
import java.io.OutputStream;
import java.math.BigDecimal;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class GenaiPricesTest {
    private static final String PRICED = "{\"total_price\":\"0.0055\","
            + "\"provider\":{\"id\":\"openai\",\"name\":\"OpenAI\"},\"model\":{\"id\":\"gpt-4o\",\"name\":\"gpt 4o\"},"
            + "\"model_price\":{\"input_mtok\":2.5,\"output_mtok\":10},\"added_later\":true}";

    private HttpServer server;
    private String requestBody;
    private String userAgent;
    private int status;
    private String responseBody;
    private String ifNoneMatch;

    @BeforeEach
    void start() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/v1/prices/calculate", exchange -> {
            requestBody = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            userAgent = exchange.getRequestHeaders().getFirst("User-Agent");
            byte[] bytes = responseBody.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", status == 200 ? "application/json" : "application/problem+json");
            exchange.sendResponseHeaders(status, bytes.length);
            try (OutputStream out = exchange.getResponseBody()) {
                out.write(bytes);
            }
        });
        server.createContext("/v1/prices", exchange -> {
            ifNoneMatch = exchange.getRequestHeaders().getFirst("If-None-Match");
            if ("\"v1\"".equals(ifNoneMatch)) {
                exchange.getResponseHeaders().set("ETag", "\"v1\"");
                exchange.sendResponseHeaders(304, -1);
                exchange.close();
                return;
            }
            byte[] bytes = "[{\"id\":\"openai\",\"name\":\"OpenAI\",\"models\":[]}]".getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.getResponseHeaders().set("ETag", "\"v1\"");
            exchange.sendResponseHeaders(200, bytes.length);
            try (OutputStream out = exchange.getResponseBody()) {
                out.write(bytes);
            }
        });
        server.start();
    }

    @AfterEach
    void stop() {
        server.stop(0);
    }

    private DefaultApi api() {
        return GenaiPrices.client("http://127.0.0.1:" + server.getAddress().getPort());
    }

    @Test
    void pricesUsage() throws ApiException {
        status = 200;
        responseBody = PRICED;
        PriceRequest request = new PriceRequest()
                .model("gpt-4o")
                .providerId("openai")
                .timestamp(OffsetDateTime.parse("2025-01-01T00:00:00Z"))
                .usage(Map.of("input_tokens", new BigDecimal(1000), "output_tokens", new BigDecimal(300)));

        PriceResponse price = api().calculatePrice(request);

        assertEquals(new BigDecimal("0.0055"), new BigDecimal(price.getTotalPrice()));
        assertEquals("openai", price.getProvider().getId());
        assertEquals("gpt-4o", price.getModel().getId());
        assertEquals("genai-prices-java/" + GenaiPrices.VERSION, userAgent);
        assertTrue(GenaiPrices.VERSION.matches("\\d+\\.\\d+\\.\\d+.*"), GenaiPrices.VERSION);
        assertTrue(requestBody.contains("\"provider_id\":\"openai\""), requestBody);
        assertTrue(requestBody.contains("\"timestamp\":\"2025-01-01T00:00:00Z\""), requestBody);
    }

    @Test
    void sendsARawProviderResponse() throws ApiException {
        status = 200;
        responseBody = PRICED;
        Map<String, Object> openaiResponse = Map.of(
                "model", "gpt-4o", "usage", Map.of("prompt_tokens", 1000, "completion_tokens", 300));

        api().calculatePrice(new PriceRequest().providerId("openai").apiFlavor("chat").response(openaiResponse));

        assertTrue(requestBody.contains("\"prompt_tokens\":1000"), requestBody);
    }

    @Test
    void raisesTheProblemDetail() {
        status = 422;
        responseBody = "{\"title\":\"Unprocessable Content\",\"status\":422,\"detail\":\"Send `usage` or `response`.\"}";

        ApiException error = assertThrows(ApiException.class, () -> api().calculatePrice(new PriceRequest().model("gpt-4o")));

        assertEquals(422, error.getCode());
        assertTrue(error.getResponseBody().contains("Send `usage` or `response`."), error.getResponseBody());
    }

    @Test
    void downloadsThePriceData() throws ApiException {
        List<Object> providers = api().getPrices("\"v0\"");

        assertEquals(1, providers.size());
        assertEquals("openai", ((Map<?, ?>) providers.get(0)).get("id"));
        assertEquals("\"v0\"", ifNoneMatch);
    }

    @Test
    void reportsUnchangedPriceData() {
        ApiException unchanged = assertThrows(ApiException.class, () -> api().getPrices("\"v1\""));

        assertEquals(304, unchanged.getCode());
    }
}
