import reset
from demo import session_one

if __name__ == "__main__":
    reset.main()
    session_one()
    print("\nseeded — now run `python -c 'import demo; demo.session_two_after_restart()'` "
          "to show only the restart beat")
