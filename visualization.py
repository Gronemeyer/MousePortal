import csv
from typing import List, Tuple
import numpy as np
import matplotlib.pyplot as plt


def load_events(event_file):
    """Load event markers from a CSV log."""
    events = []
    if not event_file:
        return events
    with open(event_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                events.append({
                    "time_sent": float(row.get("time_sent")) if row.get("time_sent") else None,
                    "time_received": float(row.get("time_received")),
                    "delta": float(row.get("delta")) if row.get("delta") else None,
                    "position": float(row.get("position")),
                    "event_name": row.get("event_name", "event"),
                })
            except (ValueError, TypeError):
                continue
    return events


def plot_log(csv_file, event_file=None):
    """Plot position and speed traces with optional event markers."""
    times, positions, speeds = [], [], []
    with open(csv_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            times.append(float(row['timestamp']))
            positions.append(float(row['position']))
            speeds.append(float(row['velocity']))

    events = sorted(load_events(event_file), key=lambda e: e["time_received"])

    fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True)
    ax1.plot(times, positions)
    ax1.set_ylabel('Position')
    ax2.plot(times, speeds)
    ax2.set_ylabel('Speed')
    ax2.set_xlabel('Time (s)')

    trial_start = None
    spans = []
    markers = []
    for ev in events:
        name = ev["event_name"].lower()
        t = ev["time_received"]
        if "start" in name and "trial" in name:
            trial_start = t
        elif ("stop" in name or "end" in name) and trial_start is not None:
            spans.append((trial_start, t))
            trial_start = None
        else:
            markers.append(ev)

    for s, e in spans:
        ax1.axvline(s, color="k", linestyle="--")
        ax1.axvline(e, color="k", linestyle="--")
        ax1.axvspan(s, e, color="gray", alpha=0.2)
        ax2.axvline(s, color="k", linestyle="--")
        ax2.axvline(e, color="k", linestyle="--")
        ax2.axvspan(s, e, color="gray", alpha=0.2)

    if markers:
        m_times = [m["time_received"] for m in markers]
        pos_vals = [np.interp(t, times, positions) for t in m_times]
        speed_vals = [np.interp(t, times, speeds) for t in m_times]
        ax1.scatter(m_times, pos_vals, color="r", marker="o")
        ax2.scatter(m_times, speed_vals, color="r", marker="o")

    plt.tight_layout()
    plt.show()


def plot_sync(event_file):
    """Visualize clock offset and jitter using the event log."""
    events = load_events(event_file)
    times_sent = [e['time_sent'] for e in events if e['time_sent'] is not None]
    times_recv = [e['time_received'] for e in events if e['time_sent'] is not None]
    deltas = [e['delta'] for e in events if e['delta'] is not None]
    if not times_sent:
        print('No timestamped events found.')
        return
    jitter = [abs(deltas[i] - deltas[i-1]) for i in range(1, len(deltas))]

    fig, (ax1, ax2) = plt.subplots(2, 1)
    ax1.scatter(times_sent, times_recv, s=10)
    ax1.plot([min(times_sent), max(times_sent)], [min(times_sent), max(times_sent)], 'k--')
    ax1.set_xlabel('time sent (parent)')
    ax1.set_ylabel('time received (child)')
    ax1.set_title('Clock Synchronization')

    ax2.plot(deltas, label='offset (s)')
    ax2.plot(range(1, len(deltas)), jitter, label='jitter (s)', linestyle='--')
    ax2.set_xlabel('event index')
    ax2.set_ylabel('seconds')
    ax2.legend()

    plt.tight_layout()
    plt.show()


if __name__ == '__main__':
    import sys
    if len(sys.argv) == 3:
        plot_log(sys.argv[1], sys.argv[2])
        plot_sync(sys.argv[2])
    else:
        plot_log(sys.argv[1])
