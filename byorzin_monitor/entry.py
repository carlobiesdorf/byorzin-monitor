# Ponto de entrada do comando `byorzin-monitor`. Os hooks e a status line do Claude Code rodam a
# cada evento, então são despachados aqui direto, sem carregar argparse/urllib/cli (bem mais rápido).
# Todo o resto vai para cli.main.
import sys


def main(argv=None):
    args = sys.argv[1:] if argv is None else list(argv)
    if len(args) == 1 and args[0] == "hook":
        from byorzin_monitor.hooks.hook import main as m
        return m()
    if len(args) == 1 and args[0] == "statusline":
        from byorzin_monitor.hooks.statusline import main as m
        return m()
    from byorzin_monitor.cli import main as m
    return m(args)


if __name__ == "__main__":
    sys.exit(main())
