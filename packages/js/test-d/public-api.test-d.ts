import {
  calcPrice,
  type ExtractedUsage,
  extractUsage,
  findProvider,
  type PriceCalculationResult,
  type PriceOptions,
  type Provider,
  type ProviderDataPayload,
  type ProviderFindOptions,
  type StorageFactoryParams,
  updatePrices,
  type Usage,
  waitForUpdate,
} from '@pydantic/genai-prices'
import { expectNotAssignable, expectType } from 'tsd'

expectType<(usage: Usage, modelId: string, options?: PriceOptions) => PriceCalculationResult>(calcPrice)
expectType<(provider: Provider, responseData: unknown, apiFlavor?: string) => ExtractedUsage>(extractUsage)
expectType<(options: ProviderFindOptions) => Provider | undefined>(findProvider)
expectType<(factory: (options: StorageFactoryParams) => void) => void>(updatePrices)
expectType<() => Promise<null | Provider[]>>(waitForUpdate)

type IsExactlyUnknown<Value> = unknown extends Value ? ([Value] extends [unknown] ? true : false) : false
type AssertFalse<Value extends false> = Value

declare const providerDataPayloadIsUnknown: AssertFalse<IsExactlyUnknown<ProviderDataPayload>>
declare const unknownProviderData: unknown
declare const providerDataPayload: ProviderDataPayload

expectType<false>(providerDataPayloadIsUnknown)
expectNotAssignable<ProviderDataPayload>(unknownProviderData)

updatePrices((params) => {
  expectType<(data: ProviderDataPayload) => void>(params.setProviderData)
  params.setProviderData(providerDataPayload)
})
