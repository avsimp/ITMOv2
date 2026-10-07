subscribers = set()


def subscribe(name):
    if not name.strip():
        raise ValueError("empty name")
    subscribers.add(name.strip())
    return {"subscribed": True}


def unsubscribe(name):
    name = name.strip()
    if not name:
        raise ValueError("empty name")
    if name not in subscribers:
        return {"unsubscribed": False}
    subscribers.remove(name)
    return {"unsubscribed": True}


def list_subscribers():
    return sorted(subscribers)
