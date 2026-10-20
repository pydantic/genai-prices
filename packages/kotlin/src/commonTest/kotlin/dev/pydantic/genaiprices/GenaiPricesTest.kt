package dev.pydantic.genaiprices

import dev.pydantic.genaiprices.models.PriceRequest
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.content.TextContent
import io.ktor.http.headersOf
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonObject
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlin.time.Instant

private const val PRICED = """{"input_price":"0.0025","output_price":"0.003","total_price":"0.0055",
"provider":{"id":"openai","name":"OpenAI"},"model":{"id":"gpt-4o","name":"gpt 4o"},
"model_price":{"input_mtok":2.5,"output_mtok":10},"added_later":true}"""

class GenaiPricesTest {
    private var requestBody = ""
    private var userAgent: String? = null

    private fun engine(status: HttpStatusCode, body: String) = MockEngine { request ->
        requestBody = (request.body as TextContent).text
        userAgent = request.headers[HttpHeaders.UserAgent]
        respond(body, status, headersOf(HttpHeaders.ContentType, "application/json"))
    }

    @Test
    fun pricesUsage() = runTest {
        val api = GenaiPrices.client(engine = engine(HttpStatusCode.OK, PRICED))

        val response = api.price(
            PriceRequest(
                model = "gpt-4o",
                providerId = "openai",
                timestamp = Instant.parse("2025-01-01T00:00:00Z"),
                usage = mapOf("input_tokens" to 1000.0, "output_tokens" to 300.0),
            ),
        )

        val price = response.body()
        assertEquals("0.0055", price.totalPrice)
        assertEquals("gpt-4o", price.model.id)
        assertEquals("2.5", price.modelPrice["input_mtok"]?.jsonPrimitive?.content)
        assertEquals("genai-prices-kotlin/$VERSION", userAgent)
        assertTrue("\"provider_id\":\"openai\"" in requestBody.filterNot { it.isWhitespace() }, requestBody)
        assertTrue("\"timestamp\":\"2025-01-01T00:00:00Z\"" in requestBody.filterNot { it.isWhitespace() }, requestBody)
    }

    @Test
    fun sendsARawProviderResponse() = runTest {
        val api = GenaiPrices.client(engine = engine(HttpStatusCode.OK, PRICED))
        val openaiResponse = buildJsonObject {
            put("model", "gpt-4o")
            putJsonObject("usage") {
                put("prompt_tokens", 1000)
                put("completion_tokens", 300)
            }
        }

        api.price(PriceRequest(providerId = "openai", apiFlavor = "chat", response = openaiResponse)).body()

        assertTrue("\"prompt_tokens\":1000" in requestBody.filterNot { it.isWhitespace() }, requestBody)
    }

    @Test
    fun reportsTheProblemStatus() = runTest {
        val problem = """{"title":"Unprocessable Content","status":422,"detail":"Send `usage` or `response`."}"""
        val api = GenaiPrices.client(engine = engine(HttpStatusCode.UnprocessableEntity, problem))

        val response = api.price(PriceRequest(model = "gpt-4o"))

        assertFalse(response.success)
        assertEquals(422, response.status)
    }
}
