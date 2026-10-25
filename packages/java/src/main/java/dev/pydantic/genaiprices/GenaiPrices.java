package dev.pydantic.genaiprices;

import dev.pydantic.genaiprices.api.DefaultApi;
import dev.pydantic.genaiprices.client.ApiClient;
import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.util.Properties;

/** Entry point for the generated genai-prices client. */
public final class GenaiPrices {
    public static final String BASE_URI = "https://genai-prices.pydantic.dev";
    public static final String VERSION = readVersion();
    /** The API counts requests per client from this header. The generated `native` client cannot set it. */
    public static final String USER_AGENT = "genai-prices-java/" + VERSION;

    private GenaiPrices() {}

    /** Returns a client for the production API. */
    public static DefaultApi client() {
        return client(BASE_URI);
    }

    /** Returns a client for the API at `baseUri`, such as a staging or local Worker. */
    public static DefaultApi client(String baseUri) {
        ApiClient apiClient = new ApiClient();
        apiClient.updateBaseUri(baseUri);
        apiClient.setRequestInterceptor(request -> request.setHeader("User-Agent", USER_AGENT));
        return new DefaultApi(apiClient);
    }

    private static String readVersion() {
        try (InputStream in = GenaiPrices.class.getResourceAsStream("version.properties")) {
            Properties properties = new Properties();
            properties.load(in);
            return properties.getProperty("version");
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }
}
