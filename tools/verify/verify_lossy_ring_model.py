"""Explore a proposed paired-DMA scratch policy; not firmware or a timing model.

DATA and HEAD reserve one destination together.  A completed pair either
publishes one payload slot or discards one scratch pair.  While one channel
has completed it waits for its peer; STOP never rearms another pair.  USB may
claim and finish payload slots in arbitrary order.
"""
from collections import deque
from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class State:
    slots: tuple  # free, dma, ready, usb
    dest: int  # -1 scratch; -2 no DMA pair
    done: int  # DATA=1, HEAD=2
    stop: bool
    drops: int


@dataclass(frozen=True)
class Ordered:
    slots: tuple  # free/dma/ready/usb/completed, indexed by sequence modulo N
    published: int
    claimed: int
    released: int
    dest: int  # -1 scratch; -2 stopped
    done: int
    stop: bool
    drops: int


def ordered_start(s):
    if s.stop or s.published >= 6:
        return Ordered(s.slots, s.published, s.claimed, s.released, -2, 0, s.stop, s.drops)
    index = s.published % len(s.slots)
    if s.slots[index] != 'free':
        return Ordered(s.slots, s.published, s.claimed, s.released, -1, 0, False, s.drops)
    slots = list(s.slots)
    slots[index] = 'dma'
    return Ordered(tuple(slots), s.published, s.claimed, s.released, index, 0, False, s.drops)


def ordered_next(s):
    if not s.stop:
        yield Ordered(s.slots, s.published, s.claimed, s.released, s.dest, s.done, True, s.drops)
    if s.claimed < s.published:
        i = s.claimed % len(s.slots)
        assert s.slots[i] == 'ready'
        slots = list(s.slots); slots[i] = 'usb'
        yield Ordered(tuple(slots), s.published, s.claimed+1, s.released, s.dest, s.done, s.stop, s.drops)
    for seq in range(s.released, s.claimed):
        i = seq % len(s.slots)
        if s.slots[i] == 'usb':
            slots = list(s.slots); slots[i] = 'completed'
            yield Ordered(tuple(slots), s.published, s.claimed, s.released, s.dest, s.done, s.stop, s.drops)
    if s.released < s.claimed and s.slots[s.released % len(s.slots)] == 'completed':
        slots = list(s.slots); slots[s.released % len(slots)] = 'free'
        yield Ordered(tuple(slots), s.published, s.claimed, s.released+1, s.dest, s.done, s.stop, s.drops)
    if s.dest == -2:
        return
    for bit in (1, 2):
        if s.done & bit:
            continue
        done = s.done | bit
        if done != 3:
            yield Ordered(s.slots, s.published, s.claimed, s.released, s.dest, done, s.stop, s.drops)
            continue
        slots = list(s.slots); published = s.published
        if s.dest >= 0:
            assert s.dest == published % len(slots) and slots[s.dest] == 'dma'
            slots[s.dest] = 'ready'; published += 1
        drops = min(2, s.drops + (s.dest == -1))
        yield ordered_start(Ordered(tuple(slots), published, s.claimed, s.released, -2, 0, s.stop, drops))


def ordered_check():
    initial = ordered_start(Ordered(('free',)*3, 0, 0, 0, -2, 0, False, 0))
    todo = deque([initial]); visited = {initial}; edges = 0
    while todo:
        s = todo.popleft()
        assert 0 <= s.released <= s.claimed <= s.published <= 6
        assert s.published - s.released <= len(s.slots)
        for seq in range(s.released, s.published):
            state = s.slots[seq % len(s.slots)]
            assert state in (('usb', 'completed') if seq < s.claimed else ('ready',))
        assert s.slots.count('dma') == (s.dest >= 0)
        for n in ordered_next(s):
            edges += 1
            assert all(not (a in ('usb', 'completed') and b == 'dma') for a, b in zip(s.slots, n.slots))
            if n not in visited:
                visited.add(n); todo.append(n)
    assert any(s.drops and s.published > 3 for s in visited)
    assert any(s.stop and s.dest == -2 and s.released == s.published for s in visited)
    return {'states': len(visited), 'transitions': edges, 'max_published': 6,
            'scope': 'Abstract ordered claim and prefix release, arbitrary USB completion; scratch drops consume no published sequence. Bounded model, not actual CP/AP mailbox or hardware execution.'}


def start(s):
    if s.stop:
        return State(s.slots, -2, 0, True, s.drops)
    try:
        index = s.slots.index('free')
    except ValueError:
        return State(s.slots, -1, 0, False, s.drops)
    slots = list(s.slots)
    slots[index] = 'dma'
    return State(tuple(slots), index, 0, False, s.drops)


def successors(s):
    if not s.stop:
        yield State(s.slots, s.dest, s.done, True, s.drops)
    for i, slot in enumerate(s.slots):
        if slot in ('ready', 'usb'):
            slots = list(s.slots)
            slots[i] = 'usb' if slot == 'ready' else 'free'
            yield State(tuple(slots), s.dest, s.done, s.stop, s.drops)
    if s.dest == -2:
        return
    for bit in (1, 2):
        if s.done & bit:
            continue
        done = s.done | bit
        if done != 3:
            yield State(s.slots, s.dest, done, s.stop, s.drops)
            continue
        slots = list(s.slots)
        if s.dest >= 0:
            assert slots[s.dest] == 'dma'
            slots[s.dest] = 'ready'
        # Saturate the test counter to keep the state space finite.
        drops = min(2, s.drops + (s.dest == -1))
        yield start(State(tuple(slots), -2, 0, s.stop, drops))


def main():
    initial = start(State(('free',)*3, -2, 0, False, 0))
    todo = deque([initial])
    visited = {initial}
    edges = 0
    while todo:
        s = todo.popleft()
        assert s.slots.count('dma') == (1 if s.dest >= 0 else 0)
        assert s.dest < 0 or s.slots[s.dest] == 'dma'
        assert not (s.dest == -2 and s.done)
        for n in successors(s):
            edges += 1
            # Existing USB ownership never becomes DMA, even across STOP.
            assert all(not (a == 'usb' and b == 'dma') for a, b in zip(s.slots, n.slots))
            if n not in visited:
                visited.add(n)
                todo.append(n)
    assert any(s.dest == -1 and s.drops for s in visited)
    assert any(s.stop and s.dest == -2 and all(x == 'free' for x in s.slots) for s in visited)
    report = {'status': 'passed', 'states': len(visited), 'transitions': edges,
              'ordered_model': ordered_check(),
              'scope': 'Abstract three payload slots plus separate scratch, paired completion and arbitrary USB releases; no real DMA register, cache, ordering, AP/CP ABI, SDR frequency axis, timing or hardware proof.',
              'design': 'Coordinate DATA/HEAD at pair boundary, choose free payload else discard scratch; never overwrite USB-owned slot, stop rearms nothing.'}
    output = Path('records/usb/geometry-lossy-ring-model.json')
    output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
