# plex-meta-migrator

Migrate locked metadata fields or playlists from one Plex library to another. This tool finds matching media items between a source and destination library (by filename) and copies locked metadata fields or recreates playlists on the destination.

## Features

### Metadata Migration (default)

Copies locked metadata fields from source to destination items, including:

- Simple fields: title, summary, tagline, sort title, studio, content rating, etc.
- Tag fields: collections, genres, directors, writers, labels, moods, styles, etc.
- Images: poster (thumb) and background art

### Playlist Migration (`--playlist`)

Copies a playlist from one server to another by matching playlist items to the destination library by filename. Smart playlists are not supported.

## Usage (Docker)

Docker images are available from Docker Hub at [`cdzombak/plex-meta-migrator`](https://hub.docker.com/r/cdzombak/plex-meta-migrator).

### Running

The Docker image stores credentials in `/data/.creds.json`. Mount a volume to `/data` to persist credentials across runs:

```bash
# Create a local directory for credentials
mkdir -p ~/.plex-meta-migrator

# Run interactively with persistent credentials
docker run -it --rm \
  -v ~/.plex-meta-migrator:/data \
  cdzombak/plex-meta-migrator
```

On first run, you'll be prompted for Plex.tv credentials. After authentication, the token is saved to the mounted volume and reused automatically on subsequent runs.

### Direct Connection

```bash
docker run -it --rm \
  cdzombak/plex-meta-migrator \
  --source-url http://192.168.1.100:32400 \
  --source-token YOUR_SOURCE_TOKEN \
  --dest-url http://192.168.1.101:32400 \
  --dest-token YOUR_DEST_TOKEN
```

### Building Locally

```bash
docker build -t plex-meta-migrator .
```

## Usage (Python)

### Installation

Requires Python 3.10+.

```bash
git clone https://github.com/cdzombak/plex-meta-migrator.git
cd plex-meta-migrator
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Running

```bash
python plex_meta_migrator.py
```

The program will interactively:

1. Prompt for Plex.tv credentials (with 2FA support), or use cached credentials
2. Let you select source and destination servers
3. Let you select source and destination libraries
4. Find matching items by filename
5. Ask whether to perform a dry run or real migration
6. Preview or execute the metadata migration

### Credential Caching

After successful MyPlex authentication, your auth token is cached in `.creds.json`. On subsequent runs, the cached token is used automatically.

Set the `PLEX_CREDS_FILE` environment variable to change the credentials file location. Delete `.creds.json` to clear cached credentials.

## Command-Line Options

```
-v, --version          Show version and exit
--playlist             Migrate a playlist instead of metadata

Source server (direct connection):
  --source-url URL       Source Plex server URL
  --source-token TOKEN   Source Plex authentication token

Destination server (direct connection):
  --dest-url URL         Destination Plex server URL
  --dest-token TOKEN     Destination Plex authentication token

MyPlex authentication:
  -u, --username USER    Plex.tv username
  -p, --password PASS    Plex.tv password
```

## License

GNU GPL v3; see [LICENSE](LICENSE) in this repository.

## Author

Chris Dzombak

- [dzombak.com](https://www.dzombak.com)
- [GitHub @cdzombak](https://github.com/cdzombak)
