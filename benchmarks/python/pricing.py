from __future__ import annotations

import argparse
import platform
import statistics
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from time import perf_counter_ns

from genai_prices import Usage, calc_price
from genai_prices.data_snapshot import DataSnapshot, get_snapshot, set_custom_snapshot
from genai_prices.types import CalcPrice, ClauseEquals, ModelInfo, ModelPrice, PriceCalculation, Provider

DEFAULT_ITERATIONS = 10_000
DEFAULT_SAMPLES = 5
DEFAULT_WARMUP_ITERATIONS = 2_000
BENCHMARK_TIMESTAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)

PriceResult = tuple[Decimal, Decimal, Decimal]


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    usage: Usage
    model_price: ModelPrice
    expected: PriceResult

    @property
    def model_ref(self) -> str:
        return f'benchmark-{self.name}'


@dataclass(frozen=True)
class BenchmarkResult:
    case_name: str
    path_name: str
    median_ns_per_op: float
    min_ns_per_op: float
    max_ns_per_op: float


def create_cases() -> tuple[BenchmarkCase, ...]:
    _, complex_model = get_snapshot().find_provider_model('gpt-realtime', None, 'openai', None)
    complex_price = complex_model.get_prices(BENCHMARK_TIMESTAMP)

    return (
        BenchmarkCase(
            name='empty',
            usage=Usage(),
            model_price=ModelPrice(),
            expected=(Decimal(0), Decimal(0), Decimal(0)),
        ),
        BenchmarkCase(
            name='one-key',
            usage=Usage(input_tokens=1_000),
            model_price=ModelPrice(input_mtok=Decimal(2)),
            expected=(Decimal('0.002'), Decimal(0), Decimal('0.002')),
        ),
        BenchmarkCase(
            name='ordinary-two-key',
            usage=Usage(input_tokens=1_000, output_tokens=100),
            model_price=ModelPrice(input_mtok=Decimal(2), output_mtok=Decimal(10)),
            expected=(Decimal('0.002'), Decimal('0.001'), Decimal('0.003')),
        ),
        BenchmarkCase(
            name='four-key-cache-modality-overlap',
            usage=Usage(
                input_tokens=1_000,
                cache_read_tokens=400,
                input_audio_tokens=300,
                cache_audio_read_tokens=100,
            ),
            model_price=ModelPrice(
                input_mtok=Decimal(2),
                cache_read_mtok=Decimal('0.5'),
                input_audio_mtok=Decimal(3),
                cache_audio_read_mtok=Decimal('0.25'),
            ),
            expected=(Decimal('0.001575'), Decimal(0), Decimal('0.001575')),
        ),
        BenchmarkCase(
            name='complex-six-key-built-in',
            usage=Usage(
                input_tokens=1_000,
                cache_read_tokens=400,
                input_audio_tokens=300,
                cache_audio_read_tokens=100,
                output_tokens=200,
                output_audio_tokens=50,
            ),
            model_price=complex_price,
            expected=(Decimal('0.00816'), Decimal('0.0056'), Decimal('0.01376')),
        ),
    )


def create_benchmark_snapshot(cases: Sequence[BenchmarkCase]) -> DataSnapshot:
    models = [
        ModelInfo(
            id=case.model_ref,
            match=ClauseEquals(case.model_ref),
            prices=case.model_price,
        )
        for case in cases
    ]
    provider = Provider(
        id='benchmark',
        name='Local benchmark fixture',
        api_pattern=r'^benchmark://',
        models=models,
    )
    return DataSnapshot(providers=[provider], from_auto_update=False)


def direct_result(result: CalcPrice) -> PriceResult:
    return result['input_price'], result['output_price'], result['total_price']


def public_result(result: PriceCalculation) -> PriceResult:
    return result.input_price, result.output_price, result.total_price


def assert_expected_results(case: BenchmarkCase) -> None:
    direct = direct_result(case.model_price.calc_price(case.usage))
    assert direct == case.expected, f'{case.name} direct result {direct!r} != {case.expected!r}'

    public = public_result(
        calc_price(
            case.usage,
            case.model_ref,
            provider_id='benchmark',
            genai_request_timestamp=BENCHMARK_TIMESTAMP,
        )
    )
    assert public == case.expected, f'{case.name} public result {public!r} != {case.expected!r}'


def run_iterations(operation: Callable[[], object], iterations: int) -> None:
    for _ in range(iterations):
        operation()


def measure(
    case_name: str,
    path_name: str,
    operation: Callable[[], object],
    *,
    iterations: int,
    samples: int,
    warmup_iterations: int,
) -> BenchmarkResult:
    run_iterations(operation, warmup_iterations)

    sample_ns_per_op: list[float] = []
    for _ in range(samples):
        started = perf_counter_ns()
        run_iterations(operation, iterations)
        elapsed = perf_counter_ns() - started
        sample_ns_per_op.append(elapsed / iterations)

    return BenchmarkResult(
        case_name=case_name,
        path_name=path_name,
        median_ns_per_op=statistics.median(sample_ns_per_op),
        min_ns_per_op=min(sample_ns_per_op),
        max_ns_per_op=max(sample_ns_per_op),
    )


def run_benchmarks(*, iterations: int, samples: int, warmup_iterations: int) -> list[BenchmarkResult]:
    cases = create_cases()
    set_custom_snapshot(create_benchmark_snapshot(cases))

    try:
        for case in cases:
            assert_expected_results(case)

        results: list[BenchmarkResult] = []
        for case in cases:
            results.append(
                measure(
                    case.name,
                    'direct',
                    lambda case=case: case.model_price.calc_price(case.usage),
                    iterations=iterations,
                    samples=samples,
                    warmup_iterations=warmup_iterations,
                )
            )
            results.append(
                measure(
                    case.name,
                    'public',
                    lambda case=case: calc_price(
                        case.usage,
                        case.model_ref,
                        provider_id='benchmark',
                        genai_request_timestamp=BENCHMARK_TIMESTAMP,
                    ),
                    iterations=iterations,
                    samples=samples,
                    warmup_iterations=warmup_iterations,
                )
            )
        return results
    finally:
        set_custom_snapshot(None)


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError('must be at least 1')
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Benchmark Python pricing calculation overhead.')
    parser.add_argument('--iterations', type=positive_int, default=DEFAULT_ITERATIONS)
    parser.add_argument('--samples', type=positive_int, default=DEFAULT_SAMPLES)
    parser.add_argument('--warmup-iterations', type=positive_int, default=DEFAULT_WARMUP_ITERATIONS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results = run_benchmarks(
        iterations=args.iterations,
        samples=args.samples,
        warmup_iterations=args.warmup_iterations,
    )

    implementation = platform.python_implementation()
    print(f'Python {platform.python_version()} ({implementation})')
    print(f'iterations={args.iterations} samples={args.samples} warmup_iterations={args.warmup_iterations}')
    print('case                                      path      median ns/op      min ns/op      max ns/op')
    for result in results:
        print(
            f'{result.case_name:<41} {result.path_name:<7} '
            f'{result.median_ns_per_op:>13.1f} {result.min_ns_per_op:>14.1f} {result.max_ns_per_op:>14.1f}'
        )


if __name__ == '__main__':
    sys.exit(main())
