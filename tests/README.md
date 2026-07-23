# Integration tests

These tests run Home Assistant Core and a real Recorder inside Docker. Each
test uses an isolated, temporary SQLite database. They do not contact the F454
or the production Home Assistant instance.

## Run the tests

Start Docker Desktop, then run this command from the repository root:

```sh
tests/run.sh
```

Optional `pytest` arguments:

```sh
tests/run.sh -k water -vv
```

The first run builds the image and downloads Home Assistant. Rebuild the image
after changing `tests/requirements.txt`:

```sh
docker compose -f docker-compose.test.yml build --no-cache
```

## How it works

The Docker image contains Python, Home Assistant, and the test dependencies.
Each run mounts the current repository and executes `pytest`.

Home Assistant's official test fixtures create a minimal in-memory runtime,
including Recorder backed by temporary SQLite. The tests call the import view
and verify persisted statistics.

This is not a browser-accessible Home Assistant instance. The container only
exists while the command runs and `--rm` removes it immediately afterwards, so
it may not appear as running in Docker Desktop.

The first run can take longer to build the image; subsequent runs reuse it and
usually complete in under a second.

## Current coverage

- energy and water imports with a real SQLite Recorder;
- base/kilo unit conversion;
- persisted values, sums, and metadata;
- F454 daily-history frame parsing;
- F454 history read failures;
- Recorder metadata validation.

The F454 is deliberately simulated. Its protocol still needs validation on the
real installation, but not for every code change.
