# Operations

This guide tells you how to move your data from Huckleberry and how to make a backup.

## Move from Huckleberry

**Settings > Import from Huckleberry** copies your children and their full history (sleep, feeds, nappies, potty,
pumping, growth, temperature, medicine, activities) from your Huckleberry account.

- Enter your Huckleberry email and password. The password is used only during the import. It is not stored or
  logged.
- The import runs in the background and shows its progress. You can leave the page.
- Select where the data goes. The default: each Huckleberry child becomes a new child in Frecklebubby, also when
  you already have a child with that name. Or select a child you have now: then the data of the Huckleberry
  child goes into that child, which keeps its name and birth date. This is only for a Huckleberry account with
  one child.
- You can run it again at any time. It does not make copies twice. A new run updates the rows that it imported
  before, so changes you made in Frecklebubby to imported rows are overwritten. Rows that you logged in
  Frecklebubby are not changed.
- Rows that are not valid (for example a time in the future or a bottle over 500 ml) are skipped. The result
  lists them.
- It is a copy, not a sync. Huckleberry is not changed.

> Tested with a built-in fake Huckleberry account. Not yet tested with a real Huckleberry account.

This project is not affiliated with Huckleberry Labs Inc.

## Backup

All data is in one SQLite database in the data folder (`/data` in the container, the volume `data`). The same folder
has the key for push notifications (`vapid_private.pem`). Keep the two together.

```bash
# copy the database out of the running container (safe while it runs)
docker compose exec app python -c "import sqlite3; sqlite3.connect('/data/frecklebubby.db').backup(sqlite3.connect('/data/backup.db'))"
docker compose cp app:/data/backup.db ./frecklebubby-backup.db
# podman compose has no "cp": use the container name from "podman ps", for example
podman cp frecklebubby_app_1:/data/backup.db ./frecklebubby-backup.db
```

To restore: stop the app, copy the file back to `/data/frecklebubby.db`, delete `frecklebubby.db-wal` and
`frecklebubby.db-shm` if they are in the folder (they belong to the old database), and start the app. You can also copy the whole
volume with your normal volume backup tool. You can also export a CSV for each child in **Reports**.
