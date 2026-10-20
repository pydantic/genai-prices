package dev.pydantic.genaiprices

import dev.pydantic.genaiprices.apis.DefaultApi
import io.ktor.client.engine.HttpClientEngine
import io.ktor.client.plugins.UserAgent

/** Entry point for the generated genai-prices client. */
object GenaiPrices {
    const val BASE_URL: String = "https://genai-prices.pydantic.dev"

    /** The API counts requests per client from this header. */
    const val USER_AGENT: String = "genai-prices-kotlin/$VERSION"

    /**
     * Returns a client for the API at [baseUrl].
     *
     * Pass an [engine] to use your own HTTP engine, or to test with `MockEngine`.
     */
    fun client(baseUrl: String = BASE_URL, engine: HttpClientEngine? = null): DefaultApi =
        DefaultApi(baseUrl = baseUrl, httpClientEngine = engine, httpClientConfig = { config ->
            config.install(UserAgent) { agent = USER_AGENT }
        })
}
