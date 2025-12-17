#!/usr/bin/env python3
"""
Plex Metadata Migrator

Connects to source and destination Plex servers, finds matching media items,
and will support copying locked metadata fields between them.
"""

import argparse
import json
import os
import sys
from getpass import getpass
from pathlib import Path
from typing import Any

from plexapi import CONFIG
from plexapi.exceptions import Unauthorized
from plexapi.library import LibrarySection
from plexapi.myplex import MyPlexAccount
from plexapi.playlist import Playlist
from plexapi.server import PlexServer

# Version is injected at build time by the Dockerfile
VERSION = "<dev>"

# Credentials file path - can be overridden via environment variable
CREDS_FILE = Path(
    os.environ.get("PLEX_CREDS_FILE", Path(__file__).parent / ".creds.json")
)


def get_field_value(item: Any, field_name: str) -> Any:
    """Get the value of a field from a media item."""
    field_mapping = {
        "title": "title",
        "titleSort": "titleSort",
        "originalTitle": "originalTitle",
        "sortTitle": "titleSort",
        "summary": "summary",
        "tagline": "tagline",
        "studio": "studio",
        "contentRating": "contentRating",
        "originallyAvailableAt": "originallyAvailableAt",
        "rating": "rating",
        "audienceRating": "audienceRating",
        "userRating": "userRating",
        "thumb": "thumb",
        "art": "art",
        "genre": "genres",
        "director": "directors",
        "writer": "writers",
        "producer": "producers",
        "country": "countries",
        "collection": "collections",
        "label": "labels",
        "mood": "moods",
        "style": "styles",
        "similar": "similar",
        "actor": "actors",
        "role": "roles",
    }

    attr_name = field_mapping.get(field_name, field_name)
    value = getattr(item, attr_name, None)

    if isinstance(value, list):
        if len(value) == 0:
            return None
        if hasattr(value[0], "tag"):
            return [v.tag for v in value]
        return value

    return value


def format_value(value: Any) -> str:
    """Format a value for display."""
    if value is None:
        return "(empty)"
    if isinstance(value, list):
        if len(value) == 0:
            return "(empty)"
        return ", ".join(str(v) for v in value)
    return str(value)


def get_locked_fields(item: Any) -> list[tuple[str, Any]]:
    """Get all locked fields and their values for a media item."""
    locked_fields = []

    if not hasattr(item, "fields") or not item.fields:
        return locked_fields

    for field in item.fields:
        if field.locked:
            value = get_field_value(item, field.name)
            locked_fields.append((field.name, value))

    return locked_fields


def connect_direct(url: str, token: str) -> PlexServer:
    """Connect directly to a Plex server using URL and token."""
    return PlexServer(url, token)


def load_cached_token() -> str | None:
    """Load cached auth token from credentials file."""
    if not CREDS_FILE.exists():
        return None
    try:
        with open(CREDS_FILE) as f:
            data = json.load(f)
            return data.get("auth_token")
    except (json.JSONDecodeError, OSError):
        return None


def save_cached_token(token: str) -> None:
    """Save auth token to credentials file."""
    try:
        with open(CREDS_FILE, "w") as f:
            json.dump({"auth_token": token}, f)
        # Set restrictive permissions (owner read/write only)
        CREDS_FILE.chmod(0o600)
    except OSError as e:
        print(f"Warning: Could not save credentials: {e}")


def clear_cached_token() -> None:
    """Remove cached credentials file."""
    try:
        CREDS_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def authenticate_myplex(username: str | None, password: str | None) -> MyPlexAccount:
    """Authenticate with MyPlex and return the account.

    Tries cached token first, falls back to username/password authentication.
    """
    # Try cached token first
    cached_token = load_cached_token()
    if cached_token:
        try:
            print("Using cached credentials...")
            account = MyPlexAccount(token=cached_token)
            return account
        except Unauthorized:
            print("Cached credentials expired, re-authenticating...")
            clear_cached_token()

    # Fall back to username/password
    if not username:
        username = CONFIG.get("auth.myplex_username")
    if not password:
        password = CONFIG.get("auth.myplex_password")

    if not username:
        username = input("Plex.tv username: ").strip()
    if not password:
        password = getpass("Plex.tv password: ")

    print(f"Authenticating with Plex.tv as {username}...")

    try:
        account = MyPlexAccount(username, password)
    except Unauthorized as e:
        if "verification code" in str(e).lower() or "1029" in str(e):
            code = input("2FA verification code: ").strip()
            account = MyPlexAccount(username, password, code=code)
        else:
            raise

    # Cache the token for future use
    save_cached_token(account.authToken)
    print("Credentials cached for future use.")

    return account


def select_server(account: MyPlexAccount, prompt: str) -> PlexServer:
    """Allow user to select a server from their MyPlex account."""
    resources = [r for r in account.resources() if "server" in r.provides]

    if not resources:
        print("No Plex servers found on this account.")
        sys.exit(1)

    if len(resources) == 1:
        print(f"Connecting to server: {resources[0].name}...")
        return resources[0].connect()

    print(f"\n{prompt}")
    print("Available servers:")
    for i, resource in enumerate(resources, 1):
        print(f"  {i}. {resource.name}")

    while True:
        try:
            choice = input("\nSelect a server (number): ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(resources):
                print(f"Connecting to server: {resources[idx].name}...")
                return resources[idx].connect()
            print(f"Please enter a number between 1 and {len(resources)}")
        except ValueError:
            print("Please enter a valid number")
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            sys.exit(0)


def select_library(plex: PlexServer, prompt: str) -> LibrarySection:
    """Allow user to select a library from available sections."""
    sections = plex.library.sections()

    if not sections:
        print("No library sections found on server.")
        sys.exit(1)

    print(f"\n{prompt}")
    print("Available libraries:")
    for i, section in enumerate(sections, 1):
        print(f"  {i}. {section.title} ({section.type})")

    while True:
        try:
            choice = input("\nSelect a library (number): ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(sections):
                return sections[idx]
            print(f"Please enter a number between 1 and {len(sections)}")
        except ValueError:
            print("Please enter a valid number")
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            sys.exit(0)


def get_item_filenames(item: Any) -> set[str]:
    """Get the set of filenames (without path) for a media item."""
    filenames = set()
    if hasattr(item, "iterParts"):
        for part in item.iterParts():
            if part and part.file:
                filename = os.path.basename(part.file)
                filenames.add(filename)
    return filenames


def get_item_display_name(item: Any) -> str:
    """Generate a display name for an item (title + year if available)."""
    name = item.title
    if hasattr(item, "year") and item.year:
        name = f"{item.title} ({item.year})"
    return name


def find_matching_items(
    source_section: LibrarySection, dest_section: LibrarySection
) -> list[tuple[Any, Any, str]]:
    """Find items that exist in both libraries by matching filenames."""
    print(f"\nScanning source library: {source_section.title}...")
    source_items = source_section.all()

    print(f"Scanning destination library: {dest_section.title}...")
    dest_items = dest_section.all()

    # Build lookup dict for destination items: filename -> item
    dest_lookup: dict[str, Any] = {}
    for item in dest_items:
        for filename in get_item_filenames(item):
            dest_lookup[filename] = item

    # Find matches by filename
    matches = []
    seen_pairs: set[tuple[int, int]] = set()  # Avoid duplicate matches
    for source_item in source_items:
        for filename in get_item_filenames(source_item):
            if filename in dest_lookup:
                dest_item = dest_lookup[filename]
                pair_key = (source_item.ratingKey, dest_item.ratingKey)
                if pair_key not in seen_pairs:
                    seen_pairs.add(pair_key)
                    matches.append((source_item, dest_item, filename))

    return matches


# Tag-based fields that need special handling with add* methods
# Maps field name to the method name to call
TAG_FIELD_METHODS = {
    "collection": "addCollection",
    "genre": "addGenre",
    "director": "addDirector",
    "writer": "addWriter",
    "producer": "addProducer",
    "country": "addCountry",
    "label": "addLabel",
    "mood": "addMood",
    "style": "addStyle",
    "similar": "addSimilar",
}


def copy_field_to_item(
    source_item: Any, dest_item: Any, field_name: str, value: Any
) -> None:
    """Copy a single field value to the destination item."""
    # Handle image fields specially - they need to be downloaded and re-uploaded
    if field_name == "thumb":
        # Build full URL to source image and upload to destination
        source_url = source_item._server.url(value, includeToken=True)
        dest_item.uploadPoster(url=source_url)
        dest_item.lockPoster()
    elif field_name == "art":
        # Build full URL to source image and upload to destination
        source_url = source_item._server.url(value, includeToken=True)
        dest_item.uploadArt(url=source_url)
        dest_item.lockArt()
    elif field_name in TAG_FIELD_METHODS:
        # Tag-based fields need to use add* methods, not editField
        # Value should be a list of tag names
        method_name = TAG_FIELD_METHODS[field_name]
        if hasattr(dest_item, method_name):
            method = getattr(dest_item, method_name)
            # Ensure value is a list
            if not isinstance(value, list):
                value = [value] if value else []
            if value:
                method(value, locked=True)
        else:
            # Fall back to editField if the method doesn't exist
            dest_item.editField(field_name, value, locked=True)
    else:
        # Use editField for most fields - it handles the API call
        dest_item.editField(field_name, value, locked=True)


def preview_metadata_migration(
    matches: list[tuple[Any, Any, str]],
) -> tuple[int, int]:
    """Preview what locked metadata would be copied (dry run).

    Returns:
        Tuple of (items_with_locked_fields, total_fields_to_copy)
    """
    print("\n" + "=" * 60)
    print("METADATA MIGRATION PREVIEW (DRY RUN)")
    print("=" * 60)

    if not matches:
        print("\nNo matching items found between libraries.")
        return 0, 0

    items_with_locked_fields = 0
    total_fields_to_copy = 0

    for source_item, dest_item, filename in matches:
        locked_fields = get_locked_fields(source_item)

        if not locked_fields:
            continue

        items_with_locked_fields += 1
        total_fields_to_copy += len(locked_fields)

        print(f"\n{get_item_display_name(source_item)}")
        print(f"  Matched file: {filename}")
        print(f"  Would copy {len(locked_fields)} locked field(s):")

        for field_name, value in locked_fields:
            print(f"    - {field_name}: {format_value(value)}")

    print("\n" + "-" * 60)
    print(f"Summary: {len(matches)} matched items")
    print(f"         {items_with_locked_fields} items with locked fields")
    print(f"         {total_fields_to_copy} total fields would be copied")

    return items_with_locked_fields, total_fields_to_copy


def perform_metadata_migration(
    matches: list[tuple[Any, Any, str]],
) -> tuple[int, int, int]:
    """Perform the actual metadata migration.

    Returns:
        Tuple of (items_migrated, fields_copied, errors)
    """
    print("\n" + "=" * 60)
    print("PERFORMING METADATA MIGRATION")
    print("=" * 60)

    if not matches:
        print("\nNo matching items found between libraries.")
        return 0, 0, 0

    items_migrated = 0
    fields_copied = 0
    errors = 0

    for source_item, dest_item, filename in matches:
        locked_fields = get_locked_fields(source_item)

        if not locked_fields:
            continue

        print(f"\n{get_item_display_name(source_item)}")
        print(f"  Matched file: {filename}")

        item_had_error = False
        for field_name, value in locked_fields:
            try:
                copy_field_to_item(source_item, dest_item, field_name, value)
                print(f"  Copied {field_name}: {format_value(value)}")
                fields_copied += 1
            except Exception as e:
                print(f"  ERROR copying {field_name}: {e}")
                errors += 1
                item_had_error = True

        if not item_had_error:
            items_migrated += 1

    print("\n" + "-" * 60)
    print("Migration complete:")
    print(f"  {items_migrated} items migrated successfully")
    print(f"  {fields_copied} fields copied")
    if errors:
        print(f"  {errors} errors encountered")

    return items_migrated, fields_copied, errors


def prompt_run_mode() -> bool:
    """Ask the user whether to perform a dry run or real run.

    Returns:
        True for real run, False for dry run
    """
    print("\n" + "-" * 60)
    print("Run mode:")
    print("  1. Dry run (preview only, no changes)")
    print("  2. Real run (actually migrate metadata)")

    while True:
        try:
            choice = input("\nSelect run mode (1 or 2): ").strip()
            if choice == "1":
                return False
            elif choice == "2":
                confirm = (
                    input("Are you sure you want to migrate metadata? (yes/no): ")
                    .strip()
                    .lower()
                )
                if confirm == "yes":
                    return True
                print("Migration cancelled.")
                return False
            print("Please enter 1 or 2")
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            sys.exit(0)


# --- Playlist Migration Functions ---


def select_playlist(server: PlexServer) -> Playlist:
    """Allow user to select a playlist from the server."""
    all_playlists = server.playlists()

    # Filter out smart playlists (they can't be meaningfully migrated)
    playlists = [p for p in all_playlists if not p.smart]

    if not playlists:
        print("No regular playlists found on server (smart playlists are not supported).")
        sys.exit(1)

    print(f"\nAvailable playlists on {server.friendlyName}:")
    for i, playlist in enumerate(playlists, 1):
        print(f"  {i}. {playlist.title} ({playlist.playlistType}, {playlist.leafCount} items)")

    while True:
        try:
            choice = input("\nSelect a playlist (number): ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(playlists):
                return playlists[idx]
            print(f"Please enter a number between 1 and {len(playlists)}")
        except ValueError:
            print("Please enter a valid number")
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            sys.exit(0)


def find_matching_playlist_items(
    playlist: Playlist, dest_section: LibrarySection
) -> tuple[list[Any], list[Any]]:
    """Match playlist items to destination library items by filename.

    Returns:
        Tuple of (matched_items, unmatched_items) where matched_items are
        destination library items in playlist order.
    """
    print(f"\nScanning playlist: {playlist.title} ({playlist.leafCount} items)...")
    playlist_items = playlist.items()

    print(f"Scanning destination library: {dest_section.title}...")
    dest_items = dest_section.all()

    # Build lookup dict for destination items: filename -> item
    dest_lookup: dict[str, Any] = {}
    for item in dest_items:
        for filename in get_item_filenames(item):
            dest_lookup[filename] = item

    # Match playlist items by filename, preserving order
    matched_items = []
    unmatched_items = []

    for playlist_item in playlist_items:
        filenames = get_item_filenames(playlist_item)
        matched = False
        for filename in filenames:
            if filename in dest_lookup:
                matched_items.append(dest_lookup[filename])
                matched = True
                break
        if not matched:
            unmatched_items.append(playlist_item)

    return matched_items, unmatched_items


def prompt_playlist_title(default_title: str) -> str:
    """Prompt for destination playlist title with a default value."""
    print(f"\nDestination playlist title (default: {default_title})")
    try:
        title = input("Title (press Enter for default): ").strip()
        return title if title else default_title
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        sys.exit(0)


def preview_playlist_migration(
    playlist: Playlist, matched_items: list[Any], unmatched_items: list[Any]
) -> None:
    """Preview what playlist would be created (dry run)."""
    print("\n" + "=" * 60)
    print("PLAYLIST MIGRATION PREVIEW (DRY RUN)")
    print("=" * 60)

    print(f"\nSource playlist: {playlist.title}")
    print(f"Total items: {playlist.leafCount}")
    print(f"Matched items: {len(matched_items)}")
    print(f"Unmatched items: {len(unmatched_items)}")

    if matched_items:
        print("\nItems that would be added to new playlist:")
        for item in matched_items[:10]:  # Show first 10
            print(f"  - {get_item_display_name(item)}")
        if len(matched_items) > 10:
            print(f"  ... and {len(matched_items) - 10} more")

    if unmatched_items:
        print("\nWARNING: The following items could not be matched:")
        for item in unmatched_items[:10]:  # Show first 10
            print(f"  - {get_item_display_name(item)}")
        if len(unmatched_items) > 10:
            print(f"  ... and {len(unmatched_items) - 10} more")

    print("\n" + "-" * 60)
    print("Summary:")
    print(f"  {len(matched_items)} of {playlist.leafCount} items would be migrated")
    if unmatched_items:
        print(f"  {len(unmatched_items)} items could not be matched (will be skipped)")


def perform_playlist_migration(
    dest_server: PlexServer, title: str, matched_items: list[Any]
) -> Playlist | None:
    """Create a new playlist on the destination server with matched items.

    Returns:
        The created Playlist, or None if no items to add.
    """
    print("\n" + "=" * 60)
    print("PERFORMING PLAYLIST MIGRATION")
    print("=" * 60)

    if not matched_items:
        print("\nNo matched items to create playlist.")
        return None

    print(f"\nCreating playlist '{title}' with {len(matched_items)} items...")

    try:
        new_playlist = dest_server.createPlaylist(title=title, items=matched_items)
        print(f"Successfully created playlist: {new_playlist.title}")
        print(f"  Items: {new_playlist.leafCount}")
        return new_playlist
    except Exception as e:
        print(f"ERROR creating playlist: {e}")
        return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate metadata or playlists between Plex libraries",
        epilog="""
Authentication methods (in order of precedence):
  1. Direct: --source-url/--source-token and --dest-url/--dest-token
  2. Config file: ~/.config/plexapi/config.ini
  3. Environment: PLEXAPI_AUTH_* variables
  4. MyPlex: --username/--password or prompted interactively

If using MyPlex authentication, you can select source and destination
servers interactively from your available servers.
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--version", "-v", action="version", version=f"%(prog)s {VERSION}"
    )

    # Mode selection
    parser.add_argument(
        "--playlist",
        action="store_true",
        help="Migrate a playlist instead of metadata",
    )

    # Direct connection options for source
    source_group = parser.add_argument_group("Source server (direct connection)")
    source_group.add_argument("--source-url", help="Source Plex server URL")
    source_group.add_argument("--source-token", help="Source Plex authentication token")

    # Direct connection options for destination
    dest_group = parser.add_argument_group("Destination server (direct connection)")
    dest_group.add_argument("--dest-url", help="Destination Plex server URL")
    dest_group.add_argument(
        "--dest-token", help="Destination Plex authentication token"
    )

    # MyPlex connection options
    myplex_group = parser.add_argument_group("MyPlex authentication")
    myplex_group.add_argument("--username", "-u", help="Plex.tv username")
    myplex_group.add_argument("--password", "-p", help="Plex.tv password")

    args = parser.parse_args()

    try:
        account: MyPlexAccount | None = None

        # Connect to source server
        if args.source_url and args.source_token:
            print(f"Connecting to source server at {args.source_url}...")
            source_server = connect_direct(args.source_url, args.source_token)
        else:
            account = authenticate_myplex(args.username, args.password)
            source_server = select_server(account, "Select SOURCE server:")

        print(f"Connected to source: {source_server.friendlyName}")

        # Connect to destination server
        if args.dest_url and args.dest_token:
            print(f"\nConnecting to destination server at {args.dest_url}...")
            dest_server = connect_direct(args.dest_url, args.dest_token)
        else:
            # Reuse the same account if we authenticated via MyPlex
            if account is None:
                account = authenticate_myplex(args.username, args.password)
            dest_server = select_server(account, "Select DESTINATION server:")

        print(f"Connected to destination: {dest_server.friendlyName}")

        if args.playlist:
            # Playlist migration mode
            dest_library = select_library(
                dest_server,
                f"Select DESTINATION library from {dest_server.friendlyName}:",
            )
            playlist = select_playlist(source_server)
            matched_items, unmatched_items = find_matching_playlist_items(
                playlist, dest_library
            )

            # Ask for destination playlist title
            dest_title = prompt_playlist_title(playlist.title)

            # Ask user for run mode
            real_run = prompt_run_mode()

            if real_run:
                perform_playlist_migration(dest_server, dest_title, matched_items)
            else:
                preview_playlist_migration(playlist, matched_items, unmatched_items)
        else:
            # Metadata migration mode (default)
            source_library = select_library(
                source_server,
                f"Select SOURCE library from {source_server.friendlyName}:",
            )
            dest_library = select_library(
                dest_server,
                f"Select DESTINATION library from {dest_server.friendlyName}:",
            )

            # Find matching items
            matches = find_matching_items(source_library, dest_library)

            # Ask user for run mode
            real_run = prompt_run_mode()

            if real_run:
                perform_metadata_migration(matches)
            else:
                preview_metadata_migration(matches)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
