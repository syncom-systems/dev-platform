"""Representative application: pure Python with one pinned third-party dependency."""


def add(a, b):
    return a + b


def banner():
    import six

    return six.ensure_str("locked-app")


def main():
    print(f"{banner()} {add(1, 2)}")


if __name__ == "__main__":
    main()
