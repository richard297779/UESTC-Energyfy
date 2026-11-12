import sys

if len(sys.argv) > 1 and sys.argv[1] in {"check", "run", "login", "notify"}:
    from .cli import main

    sys.exit(main(sys.argv))

from .app import main

main()
