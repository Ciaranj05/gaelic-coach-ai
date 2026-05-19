# Real Video Analysis Pipeline

The current Vercel app can generate AI reports from notes/transcripts, but it cannot yet watch a YouTube/Veo video directly.

To create true match analysis, the app needs a backend video worker.

## Why this cannot live fully inside Vercel

Vercel serverless functions are not ideal for long-running video jobs because video processing requires:

- downloading large files
- running FFmpeg
- extracting frames/audio
- storing temporary files
- queueing jobs that may take minutes
- retrying failed processing

The frontend should stay on Vercel. The heavy video analysis should run on a worker service.

## Recommended Architecture

```text
Vercel Frontend
  -> /api/create-analysis-job
  -> Video Worker API
  -> Download video or receive uploaded file
  -> FFmpeg extracts audio + frames
  -> OpenAI analyses transcript + selected frames
  -> Structured coaching report returned
  -> Report saved to database
```

## Services

### Frontend
- Vercel
- Next.js
- Tailwind

### Worker
Use one of:
- Railway
- Render
- Fly.io
- DigitalOcean App Platform

### Storage
Use one of:
- Cloudflare R2
- AWS S3
- Supabase Storage

### Database
Use one of:
- Supabase Postgres
- Neon Postgres

### Video tools
- yt-dlp for public video links
- FFmpeg for audio/frame extraction

### AI
- OpenAI for transcript and frame-based analysis

## Processing Steps

1. Coach submits YouTube/Veo/Vimeo link.
2. Vercel creates an analysis job.
3. Worker downloads video with yt-dlp where permitted.
4. Worker extracts:
   - audio track
   - frames every 10-20 seconds
   - highlight candidate clips later
5. Audio is transcribed.
6. Frames and transcript are passed to OpenAI.
7. OpenAI returns structured JSON:
   - match summary
   - key insights
   - training focus
   - timeline
   - coaching recommendations
8. Frontend displays report.

## MVP Analysis Prompt Inputs

The first real version should analyse:

- scoreline
- team names
- user notes
- transcript
- extracted frames
- known coaching framework

## Limits of Version 1

Version 1 will not perfectly detect every event automatically.

It can realistically produce:

- match summary
- attacking/defensive themes
- coaching priorities
- likely momentum shifts
- training plan suggestions
- questions for coach review

## Future Advanced Features

- automatic score detection
- player tracking
- heatmaps
- kickout recognition
- turnover tagging
- possession chains
- clip generation
- player development reports
