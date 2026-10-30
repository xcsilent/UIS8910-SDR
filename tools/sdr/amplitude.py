"""Host-only level diagnostics for a bounded, unmodified native12 IQ window."""
import numpy as np


def native12_amplitude(lane0, lane1):
    a = np.asarray(lane0, dtype=np.float64)
    b = np.asarray(lane1, dtype=np.float64)
    if a.shape != b.shape or not a.size:
        raise ValueError('matching nonempty native12 lanes required')
    return dict(
        sampled_complex_samples=a.size,
        max_abs_lane_native12=int(round(max(np.abs(a).max(), np.abs(b).max()))),
        lane_rms_native12=float(np.sqrt((np.sum(a*a)+np.sum(b*b))/(2*a.size))),
        near_rail_lane_fraction=float((np.count_nonzero(np.abs(a)>=2040)+
                                      np.count_nonzero(np.abs(b)>=2040))/(2*a.size)),
        scope='Selected raw analysis window before DC removal; not whole-capture coverage. '
              'Near rail means abs(lane)>=2040. No digital clipping does not rule out analog compression.')
