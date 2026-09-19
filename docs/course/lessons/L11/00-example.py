from collections import deque
recent = deque(maxlen=3)
events = [("read", "same"), ("read", "same"), ("read", "same")]
for event in events:
    recent.append(event)
    repeated = len(recent) == 3 and len(set(recent)) == 1
    print("stop" if repeated else "continue")
