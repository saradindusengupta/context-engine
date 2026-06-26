from config import DB_PATH
import os


def main():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    print("db wiped")


if __name__ == "__main__":
    main()
