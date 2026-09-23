# Phase 11.1 — YouTube Channel Monitoring and Batch Approval

## Model and migration

The knowledge schema now contains typed `monitored_channels` and
`channel_video_candidates` tables. A monitored channel is identified by its
stable YouTube channel ID, not display name. Candidates are unique per channel
and stable YouTube video ID. Candidate status is NEW, SELECTED, IMPORTING,
IMPORTED, IGNORED, or FAILED.

Migration `7c4e2b1f6a90` was upgraded, downgraded, upgraded again, and checked
for drift.

## Discovery and approval boundary

`YouTubeAdapter.resolve_channel` and `list_channel_videos` use the existing
yt-dlp boundary for channel metadata and flat public video metadata only. They
do not acquire transcripts. `ChannelDiscoveryService` compares stable video
IDs with the existing source table and prior candidates. Checking a channel
only creates/updates candidates; it never invokes source ingestion.

The `/channels` owner page lists registered channels, `/channels/new`
registers one, and `/channels/{id}` presents unchecked candidate checkboxes.
`/channels/check-all` groups candidates by channel. Import endpoints accept
only IDs belonging to the relevant channel and require explicit selection.
Ignored candidates remain absent from NEW results.

## Batch import and failures

Approved candidates call the existing `ExternalKnowledgeImporter` once per
video. Each candidate is marked IMPORTING before its independent attempt and
becomes IMPORTED or FAILED afterward. One failure does not roll back successful
videos; FAILED candidates remain retryable. No lecture, research,
localization, audio, video, publication, or Canon operation is involved.

## Real QA

The existing development source identified the real Mokri channel
`UCcjn40kF25PEYNlmS8_3hdQ`. Discovery resolved it and listed 100 public video
entries; 99 candidates were new and the already imported video ID was excluded.
No candidate was imported. A fake-adapter integration test proves approval
gating and idempotent discovery. Full suite: 143 tests passed.
