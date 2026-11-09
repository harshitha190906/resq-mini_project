"""
ResQNet — tests/test_reliability.py
=====================================
Unit tests for CRC, Go-Back-N, and Leaky Bucket algorithms.

Coverage
--------
CRC
  - Textbook example (dataword "1101011011", generator "10011")
  - Codeword verification (valid and after error injection)
  - Generator validation (too short, bad chars, bad start/end)
  - Error injection (single, multi, duplicate positions, boundary)
  - All CRCPreset values produce valid checksums
  - Empty inputs / short received strings rejected

Go-Back-N
  - No-loss delivery (correct count and order)
  - Single frame loss → retransmission and eventual delivery
  - Multiple losses → all frames still delivered
  - Sequence number wrap-around
  - Window-size=1 (stop-and-wait equivalent)
  - Delivery order is always sequential
  - Event log integrity (tick ordering, DONE event present)
  - Metrics: total_transmissions > total_frames when loss occurs

Leaky Bucket
  - No-arrival run → zero drops, queue drains
  - Steady arrival at leak rate → no drops, no leftover
  - Burst arrival → overflow/drops, smooth output
  - Full bucket → all excess dropped immediately
  - Capacity and leak-rate boundary values
  - Duration=1 single-tick edge case
  - drop_rate calculation
  - Negative/missing arrival ticks treated as zero
  - Per-tick event fields are consistent (admitted+dropped == arriving)
  - Stateless tick() helper

Run with:
    python -m pytest tests/test_reliability.py -v
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.algorithms.crc import CRCEngine, CRCPreset
from app.algorithms.go_back_n import GBNSimulator, GBNEventType
from app.algorithms.leaky_bucket import LeakyBucket


# ═════════════════════════════════════════════════════════════════════════════
# CRC
# ═════════════════════════════════════════════════════════════════════════════

class TestCRCGenerate:

    def test_textbook_example_remainder(self):
        """
        Standard textbook: dataword='1101011011', generator='10011'
        Expected remainder: '1110'
        """
        engine = CRCEngine("10011")
        result = engine.generate("1101011011")
        assert result.remainder == "1110"

    def test_textbook_codeword(self):
        engine = CRCEngine("10011")
        result = engine.generate("1101011011")
        assert result.codeword == "11010110111110"

    def test_padded_dataword_length(self):
        """padded = dataword + (len(generator)-1) zeros."""
        engine = CRCEngine("10011")   # checksum_length = 4
        result = engine.generate("110")
        assert len(result.padded_dataword) == len("110") + 4
        assert result.padded_dataword.endswith("0000")

    def test_codeword_starts_with_dataword(self):
        engine = CRCEngine("10011")
        data   = "10110010"
        result = engine.generate(data)
        assert result.codeword.startswith(data)

    def test_codeword_ends_with_remainder(self):
        engine = CRCEngine("10011")
        result = engine.generate("1101011011")
        assert result.codeword.endswith(result.remainder)

    def test_remainder_length_equals_checksum_length(self):
        engine = CRCEngine("10011")
        result = engine.generate("1010101010")
        assert len(result.remainder) == engine.checksum_length

    def test_generate_returns_correct_generator(self):
        engine = CRCEngine("100000111")
        result = engine.generate("11001010")
        assert result.generator == "100000111"

    def test_division_steps_non_empty(self):
        engine = CRCEngine("10011")
        result = engine.generate("1101011011")
        assert len(result.division_steps) > 0

    def test_single_bit_dataword(self):
        engine = CRCEngine("11")   # smallest valid generator
        result = engine.generate("1")
        assert len(result.remainder) == 1
        assert isinstance(result.codeword, str)

    def test_to_dict_contains_all_keys(self):
        engine = CRCEngine("10011")
        d = engine.generate("1101").to_dict()
        for key in ("dataword", "generator", "padded_dataword",
                    "remainder", "codeword", "division_steps"):
            assert key in d

    @pytest.mark.parametrize("preset", [
        CRCPreset.CRC4, CRCPreset.CRC8, CRCPreset.CRC16, CRCPreset.CRC_CCITT
    ])
    def test_all_presets_generate_valid_remainder(self, preset):
        engine = CRCEngine(preset)
        result = engine.generate("1101011011")
        assert len(result.remainder) == engine.checksum_length
        assert all(b in "01" for b in result.remainder)


class TestCRCVerify:

    def test_valid_codeword_passes(self):
        engine = CRCEngine("10011")
        gen    = engine.generate("1101011011")
        verify = engine.verify(gen.codeword)
        assert verify.valid is True

    def test_syndrome_is_all_zeros_for_valid(self):
        engine = CRCEngine("10011")
        gen    = engine.generate("1101011011")
        verify = engine.verify(gen.codeword)
        assert all(b == "0" for b in verify.syndrome)

    def test_single_bit_error_detected(self):
        engine = CRCEngine("10011")
        gen    = engine.generate("1101011011")
        bad    = engine.inject_errors(gen.codeword, [0])
        verify = engine.verify(bad.corrupted)
        assert verify.valid is False

    def test_multi_bit_error_detected(self):
        engine = CRCEngine("10011")
        gen    = engine.generate("1101011011")
        bad    = engine.inject_errors(gen.codeword, [0, 5, 9])
        verify = engine.verify(bad.corrupted)
        assert verify.valid is False

    def test_verify_syndrome_length(self):
        engine = CRCEngine("10011")
        gen    = engine.generate("1101011011")
        verify = engine.verify(gen.codeword)
        assert len(verify.syndrome) == engine.checksum_length

    def test_verify_to_dict_keys(self):
        engine = CRCEngine("10011")
        gen    = engine.generate("1101011011")
        d      = engine.verify(gen.codeword).to_dict()
        for key in ("received", "generator", "syndrome", "valid", "division_steps"):
            assert key in d

    def test_received_too_short_raises(self):
        engine = CRCEngine("10011")   # generator len=5; need at least 5
        with pytest.raises(ValueError, match="shorter"):
            engine.verify("101")

    def test_all_presets_verify_their_own_codewords(self):
        for preset in [CRCPreset.CRC4, CRCPreset.CRC8]:
            engine = CRCEngine(preset)
            gen    = engine.generate("1101011011")
            assert engine.verify(gen.codeword).valid


class TestCRCErrorInjection:

    def test_single_flip(self):
        engine = CRCEngine("10011")
        orig   = "1101011011"
        result = engine.inject_errors(orig, [3])
        # Position 3: original '1' → should become '0'
        assert result.corrupted[3] != orig[3]
        assert result.num_errors == 1
        assert result.flipped_positions == [3]

    def test_multi_flip(self):
        engine = CRCEngine("10011")
        orig   = "11010110111110"
        result = engine.inject_errors(orig, [0, 5, 13])
        assert result.num_errors == 3
        for p in [0, 5, 13]:
            assert result.corrupted[p] != orig[p]

    def test_duplicate_positions_deduplicated(self):
        engine = CRCEngine("10011")
        result = engine.inject_errors("1101", [1, 1, 1])
        assert result.num_errors == 1
        assert result.flipped_positions == [1]

    def test_flip_then_flip_restores_original(self):
        """Flipping a bit twice must restore the original string."""
        engine = CRCEngine("10011")
        orig   = "1101011011"
        step1  = engine.inject_errors(orig, [2])
        step2  = engine.inject_errors(step1.corrupted, [2])
        assert step2.corrupted == orig

    def test_out_of_range_position_raises(self):
        engine = CRCEngine("10011")
        with pytest.raises(IndexError):
            engine.inject_errors("101", [10])

    def test_negative_position_raises(self):
        engine = CRCEngine("10011")
        with pytest.raises(IndexError):
            engine.inject_errors("101", [-1])

    def test_last_valid_position_accepted(self):
        engine = CRCEngine("10011")
        bits   = "11010"
        result = engine.inject_errors(bits, [4])   # index 4 = last bit
        assert result.corrupted[4] != bits[4]

    def test_inject_into_empty_raises(self):
        engine = CRCEngine("10011")
        with pytest.raises(ValueError, match="empty"):
            engine.inject_errors("", [0])


class TestCRCValidation:

    def test_generator_too_short_raises(self):
        with pytest.raises(ValueError, match="2 bits"):
            CRCEngine("1")

    def test_generator_non_binary_raises(self):
        with pytest.raises(ValueError, match="'0' and '1'"):
            CRCEngine("1A011")

    def test_generator_not_starting_with_one_raises(self):
        with pytest.raises(ValueError, match="start and end"):
            CRCEngine("01001")

    def test_generator_not_ending_with_one_raises(self):
        with pytest.raises(ValueError, match="start and end"):
            CRCEngine("10010")

    def test_empty_dataword_raises(self):
        engine = CRCEngine("10011")
        with pytest.raises(ValueError, match="empty"):
            engine.generate("")

    def test_non_binary_dataword_raises(self):
        engine = CRCEngine("10011")
        with pytest.raises(ValueError, match="'0' and '1'"):
            engine.generate("10A1")

    def test_custom_preset_enum_raises(self):
        with pytest.raises(ValueError, match="CUSTOM"):
            CRCEngine(CRCPreset.CUSTOM)

    def test_preset_enum_accepted(self):
        engine = CRCEngine(CRCPreset.CRC4)
        assert engine.generator == CRCPreset.CRC4.value


# ═════════════════════════════════════════════════════════════════════════════
# Go-Back-N
# ═════════════════════════════════════════════════════════════════════════════

class TestGBNNoLoss:

    def test_all_frames_delivered(self):
        sim    = GBNSimulator(total_frames=6, window_size=3, timeout_ticks=5)
        result = sim.run()
        assert len(result.delivered_in_order) == 6

    def test_delivered_frames_in_order(self):
        sim    = GBNSimulator(total_frames=5, window_size=2, timeout_ticks=4)
        result = sim.run()
        assert result.delivered_in_order == list(range(5))

    def test_no_timeouts_without_loss(self):
        sim    = GBNSimulator(total_frames=4, window_size=4, timeout_ticks=3)
        result = sim.run()
        assert result.total_timeouts == 0

    def test_transmissions_equal_frames_no_loss(self):
        sim    = GBNSimulator(total_frames=4, window_size=4, timeout_ticks=5)
        result = sim.run()
        assert result.total_transmissions == 4

    def test_single_frame_delivery(self):
        sim    = GBNSimulator(total_frames=1, window_size=1, timeout_ticks=3)
        result = sim.run()
        assert result.delivered_in_order == [0]
        assert result.total_transmissions == 1

    def test_done_event_present(self):
        sim    = GBNSimulator(total_frames=3, window_size=2, timeout_ticks=5)
        result = sim.run()
        types  = [e.event_type for e in result.events]
        assert GBNEventType.DONE in types

    def test_done_is_last_event(self):
        sim    = GBNSimulator(total_frames=3, window_size=2, timeout_ticks=5)
        result = sim.run()
        assert result.events[-1].event_type == GBNEventType.DONE

    def test_result_to_dict_keys(self):
        sim = GBNSimulator(total_frames=2, window_size=2, timeout_ticks=3)
        d   = sim.run().to_dict()
        for key in ("total_frames", "window_size", "delivered_in_order",
                    "total_transmissions", "total_timeouts", "events"):
            assert key in d

    def test_modulus_is_window_plus_one(self):
        sim    = GBNSimulator(total_frames=5, window_size=3, timeout_ticks=5)
        result = sim.run()
        assert result.modulus == 4


class TestGBNWithLoss:

    def test_single_loss_all_delivered(self):
        """Lose seq 0 on attempt 1; all 4 frames must still arrive."""
        sim    = GBNSimulator(
            total_frames=4, window_size=3, timeout_ticks=3,
            lost_frames={(0, 1)},
        )
        result = sim.run()
        assert len(result.delivered_in_order) == 4

    def test_single_loss_causes_retransmission(self):
        sim    = GBNSimulator(
            total_frames=4, window_size=3, timeout_ticks=3,
            lost_frames={(0, 1)},
        )
        result = sim.run()
        assert result.total_transmissions > 4

    def test_single_loss_timeout_fires(self):
        sim    = GBNSimulator(
            total_frames=4, window_size=3, timeout_ticks=3,
            lost_frames={(0, 1)},
        )
        result = sim.run()
        assert result.total_timeouts >= 1

    def test_multi_loss_all_delivered(self):
        sim    = GBNSimulator(
            total_frames=6, window_size=3, timeout_ticks=4,
            lost_frames={(0, 1), (2, 1)},
        )
        result = sim.run()
        assert len(result.delivered_in_order) == 6

    def test_loss_event_recorded(self):
        sim    = GBNSimulator(
            total_frames=3, window_size=2, timeout_ticks=3,
            lost_frames={(0, 1)},
        )
        result = sim.run()
        types  = [e.event_type for e in result.events]
        assert GBNEventType.LOSS in types

    def test_delivered_frames_are_sequential_after_loss(self):
        sim    = GBNSimulator(
            total_frames=5, window_size=3, timeout_ticks=4,
            lost_frames={(1, 1)},
        )
        result = sim.run()
        # Must arrive in ID order 0,1,2,3,4
        assert result.delivered_in_order == list(range(5))

    def test_window_size_one_stop_and_wait(self):
        """Window=1 is stop-and-wait: only one frame in flight at a time."""
        sim    = GBNSimulator(
            total_frames=3, window_size=1, timeout_ticks=2,
            lost_frames={(0, 1)},
        )
        result = sim.run()
        assert len(result.delivered_in_order) == 3

    def test_large_window_many_frames_no_loss(self):
        sim    = GBNSimulator(total_frames=20, window_size=7, timeout_ticks=5)
        result = sim.run()
        assert len(result.delivered_in_order) == 20
        assert result.total_transmissions == 20


class TestGBNEventLog:

    def test_events_non_empty(self):
        sim = GBNSimulator(total_frames=3, window_size=2, timeout_ticks=5)
        assert len(sim.run().events) > 0

    def test_ticks_non_decreasing(self):
        sim    = GBNSimulator(total_frames=4, window_size=2, timeout_ticks=5)
        result = sim.run()
        ticks  = [e.tick for e in result.events]
        assert ticks == sorted(ticks)

    def test_no_duplicate_delivered_frame_ids(self):
        """Each frame_id must be delivered exactly once."""
        sim       = GBNSimulator(total_frames=5, window_size=3, timeout_ticks=5)
        delivered = sim.run().delivered_in_order
        assert len(delivered) == len(set(delivered))

    def test_event_to_dict_keys(self):
        sim    = GBNSimulator(total_frames=2, window_size=2, timeout_ticks=5)
        result = sim.run()
        d      = result.events[0].to_dict()
        for key in ("tick", "event_type", "seq_num", "frame_id",
                    "attempt", "window_state", "description"):
            assert key in d


class TestGBNValidation:

    def test_zero_frames_raises(self):
        with pytest.raises(ValueError, match="total_frames"):
            GBNSimulator(total_frames=0, window_size=1, timeout_ticks=3)

    def test_zero_window_raises(self):
        with pytest.raises(ValueError, match="window_size"):
            GBNSimulator(total_frames=3, window_size=0, timeout_ticks=3)

    def test_zero_timeout_raises(self):
        with pytest.raises(ValueError, match="timeout_ticks"):
            GBNSimulator(total_frames=3, window_size=2, timeout_ticks=0)


# ═════════════════════════════════════════════════════════════════════════════
# Leaky Bucket
# ═════════════════════════════════════════════════════════════════════════════

class TestLeakyBucketNoArrivals:

    def test_no_arrivals_no_drops(self):
        lb     = LeakyBucket(capacity=5, leak_rate=1)
        result = lb.run({}, duration=5)
        assert result.total_dropped == 0

    def test_no_arrivals_no_admitted(self):
        lb     = LeakyBucket(capacity=5, leak_rate=1)
        result = lb.run({}, duration=5)
        assert result.total_admitted == 0

    def test_no_arrivals_zero_leaked(self):
        """With empty bucket and no arrivals, nothing leaks."""
        lb     = LeakyBucket(capacity=5, leak_rate=2)
        result = lb.run({}, duration=3)
        assert result.total_leaked == 0

    def test_no_arrivals_final_queue_zero(self):
        lb     = LeakyBucket(capacity=5, leak_rate=1)
        result = lb.run({}, duration=5)
        assert result.final_queue == 0


class TestLeakyBucketSteadyRate:

    def test_steady_equal_rate_no_drops(self):
        """Arrival rate == leak rate → no drops, queue stays at 0."""
        lb       = LeakyBucket(capacity=4, leak_rate=2)
        arrivals = {t: 2 for t in range(5)}
        result   = lb.run(arrivals, duration=5)
        assert result.total_dropped == 0

    def test_steady_equal_rate_all_leaked(self):
        lb       = LeakyBucket(capacity=4, leak_rate=2)
        arrivals = {t: 2 for t in range(5)}
        result   = lb.run(arrivals, duration=5)
        assert result.total_leaked == result.total_admitted

    def test_slow_arrival_no_drops(self):
        """Arrival rate < leak rate → queue drains every tick, no drops."""
        lb       = LeakyBucket(capacity=10, leak_rate=3)
        arrivals = {t: 1 for t in range(6)}
        result   = lb.run(arrivals, duration=6)
        assert result.total_dropped == 0


class TestLeakyBucketBurst:

    def test_burst_causes_drops(self):
        lb       = LeakyBucket(capacity=3, leak_rate=1)
        arrivals = {0: 10}   # 10 packets arrive at once; only 3 fit
        result   = lb.run(arrivals, duration=5)
        assert result.total_dropped == 7

    def test_burst_admitted_equals_capacity(self):
        lb       = LeakyBucket(capacity=3, leak_rate=1)
        arrivals = {0: 10}
        result   = lb.run(arrivals, duration=1)
        assert result.total_admitted == 3

    def test_burst_output_is_smooth(self):
        """After a burst, the bucket drains at exactly leak_rate per tick."""
        lb       = LeakyBucket(capacity=5, leak_rate=1)
        arrivals = {0: 5}
        result   = lb.run(arrivals, duration=6)
        # Tick 0: 5 arrive, 3 admitted (wait — capacity=5 so all 5 admitted),
        # then 1 leaks → queue=4. Ticks 1-5: no arrivals, 1 leaks/tick.
        # Total leaked = 5 (all 5 packets drain eventually).
        leaked_per_tick = [e.leaked for e in result.events]
        # No tick should leak more than leak_rate=1
        assert all(lk <= 1 for lk in leaked_per_tick)

    def test_drop_rate_calculation(self):
        lb       = LeakyBucket(capacity=2, leak_rate=1)
        arrivals = {0: 4}
        result   = lb.run(arrivals, duration=3)
        expected = result.total_dropped / result.total_arriving
        assert abs(result.drop_rate - expected) < 1e-9


class TestLeakyBucketFullBucket:

    def test_full_bucket_drops_all_new(self):
        """When bucket starts full (arrivals fill it instantly), extras drop."""
        lb       = LeakyBucket(capacity=2, leak_rate=1)
        arrivals = {0: 2, 1: 5}
        result   = lb.run(arrivals, duration=2)
        # Tick 0: 2 arrive → admitted 2, queue=2 → leak 1 → queue=1
        # Tick 1: 5 arrive → space=1 → admitted 1, dropped 4; queue=2 → leak 1 → queue=1
        assert result.total_dropped == 4

    def test_zero_arrivals_gradually_empties_bucket(self):
        lb       = LeakyBucket(capacity=5, leak_rate=2)
        arrivals = {0: 5}
        result   = lb.run(arrivals, duration=4)
        # tick0: arrive 5, admitted 5, leak 2 → queue 3
        # tick1: arrive 0, leak 2 → queue 1
        # tick2: arrive 0, leak 1 → queue 0
        # tick3: arrive 0, leak 0 → queue 0
        assert result.final_queue == 0


class TestLeakyBucketEvents:

    def test_event_count_equals_duration(self):
        lb     = LeakyBucket(capacity=5, leak_rate=1)
        result = lb.run({0: 2}, duration=4)
        assert len(result.events) == 4

    def test_admitted_plus_dropped_equals_arriving(self):
        lb       = LeakyBucket(capacity=3, leak_rate=1)
        arrivals = {0: 5, 1: 2, 2: 8}
        result   = lb.run(arrivals, duration=3)
        for e in result.events:
            assert e.admitted + e.dropped == e.arriving

    def test_queue_after_within_capacity(self):
        lb       = LeakyBucket(capacity=4, leak_rate=1)
        arrivals = {0: 10, 1: 10}
        result   = lb.run(arrivals, duration=5)
        for e in result.events:
            assert 0 <= e.queue_after <= lb.capacity

    def test_leaked_never_exceeds_leak_rate(self):
        lb       = LeakyBucket(capacity=10, leak_rate=3)
        arrivals = {t: 5 for t in range(6)}
        result   = lb.run(arrivals, duration=6)
        for e in result.events:
            assert e.leaked <= lb.leak_rate

    def test_event_to_dict_keys(self):
        lb     = LeakyBucket(capacity=5, leak_rate=1)
        result = lb.run({0: 3}, duration=2)
        d      = result.events[0].to_dict()
        for key in ("tick", "arriving", "admitted", "dropped",
                    "leaked", "queue_before", "queue_after", "description"):
            assert key in d

    def test_result_to_dict_keys(self):
        lb = LeakyBucket(capacity=5, leak_rate=1)
        d  = lb.run({}, duration=3).to_dict()
        for key in ("capacity", "leak_rate", "duration", "total_arriving",
                    "total_admitted", "total_dropped", "total_leaked",
                    "final_queue", "drop_rate", "events"):
            assert key in d

    def test_queue_before_equals_previous_queue_after(self):
        lb       = LeakyBucket(capacity=5, leak_rate=1)
        arrivals = {0: 3, 2: 2}
        result   = lb.run(arrivals, duration=4)
        evs      = result.events
        for i in range(1, len(evs)):
            assert evs[i].queue_before == evs[i - 1].queue_after


class TestLeakyBucketBoundary:

    def test_capacity_one_leak_rate_one(self):
        lb       = LeakyBucket(capacity=1, leak_rate=1)
        arrivals = {t: 3 for t in range(4)}
        result   = lb.run(arrivals, duration=4)
        # Each tick: space=1 (or 0 after first tick before leak),
        # admitted ≤ 1; dropped ≥ 2 per tick
        assert result.total_dropped > 0
        for e in result.events:
            assert e.queue_after <= 1

    def test_duration_one(self):
        lb       = LeakyBucket(capacity=5, leak_rate=2)
        result   = lb.run({0: 4}, duration=1)
        assert len(result.events) == 1
        assert result.total_admitted == 4
        assert result.total_leaked == 2

    def test_negative_arrivals_treated_as_zero(self):
        lb     = LeakyBucket(capacity=5, leak_rate=1)
        result = lb.run({0: -10}, duration=2)
        assert result.total_arriving == 0
        assert result.total_dropped  == 0

    def test_missing_tick_in_arrivals_is_zero(self):
        """Gaps in the arrivals dict mean zero packets that tick."""
        lb       = LeakyBucket(capacity=5, leak_rate=1)
        arrivals = {0: 3}   # tick 1 is absent
        result   = lb.run(arrivals, duration=2)
        assert result.events[1].arriving == 0

    def test_large_leak_rate_drains_immediately(self):
        """leak_rate > capacity → bucket always empty after leak."""
        lb       = LeakyBucket(capacity=3, leak_rate=10)
        arrivals = {t: 3 for t in range(5)}
        result   = lb.run(arrivals, duration=5)
        for e in result.events:
            assert e.queue_after == 0


class TestLeakyBucketValidation:

    def test_zero_capacity_raises(self):
        with pytest.raises(ValueError, match="capacity"):
            LeakyBucket(capacity=0, leak_rate=1)

    def test_negative_capacity_raises(self):
        with pytest.raises(ValueError, match="capacity"):
            LeakyBucket(capacity=-3, leak_rate=1)

    def test_zero_leak_rate_raises(self):
        with pytest.raises(ValueError, match="leak_rate"):
            LeakyBucket(capacity=5, leak_rate=0)

    def test_zero_duration_raises(self):
        lb = LeakyBucket(capacity=5, leak_rate=1)
        with pytest.raises(ValueError, match="duration"):
            lb.run({}, duration=0)


class TestLeakyBucketTickHelper:

    def test_tick_helper_admitted_and_dropped(self):
        lb    = LeakyBucket(capacity=3, leak_rate=1)
        event = lb.tick(current_queue=2, arriving=5)
        # space = 3-2=1 → admitted=1, dropped=4; queue=2+1=3 → leak1 → queue=2
        assert event.admitted == 1
        assert event.dropped  == 4
        assert event.queue_after == 2

    def test_tick_helper_out_of_range_raises(self):
        lb = LeakyBucket(capacity=3, leak_rate=1)
        with pytest.raises(ValueError):
            lb.tick(current_queue=5, arriving=0)

    def test_tick_helper_empty_bucket_no_leak(self):
        lb    = LeakyBucket(capacity=5, leak_rate=2)
        event = lb.tick(current_queue=0, arriving=0)
        assert event.leaked     == 0
        assert event.queue_after == 0
