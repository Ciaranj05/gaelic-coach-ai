import { NextResponse } from 'next/server'
import { Storage } from '@google-cloud/storage'
import { randomUUID } from 'crypto'

type UploadRequest = {
  filename?: string
  contentType?: string
  size?: number
}

function getStorageClient() {
  const projectId = process.env.GCP_PROJECT_ID
  const clientEmail = process.env.GCP_CLIENT_EMAIL
  const privateKey = process.env.GCP_PRIVATE_KEY?.replace(/\\n/g, '\n')

  if (projectId && clientEmail && privateKey) {
    return new Storage({
      projectId,
      credentials: {
        client_email: clientEmail,
        private_key: privateKey
      }
    })
  }

  return new Storage()
}

function safeFilename(filename: string) {
  return filename
    .replace(/[^a-zA-Z0-9._-]/g, '-')
    .replace(/-+/g, '-')
    .slice(0, 120)
}

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as UploadRequest
    const bucketName = process.env.GCS_UPLOAD_BUCKET

    if (!bucketName) {
      return NextResponse.json({ error: 'GCS_UPLOAD_BUCKET is not configured.' }, { status: 500 })
    }

    const filename = safeFilename(body.filename || 'match-video.mp4')
    const contentType = body.contentType || 'video/mp4'
    const objectName = `match-uploads/${new Date().toISOString().slice(0, 10)}/${randomUUID()}-${filename}`

    const storage = getStorageClient()
    const bucket = storage.bucket(bucketName)
    const file = bucket.file(objectName)

    const [uploadUrl] = await file.createResumableUpload({
      origin: process.env.NEXT_PUBLIC_APP_ORIGIN || undefined,
      metadata: {
        contentType,
        metadata: {
          originalFilename: filename,
          expectedSize: String(body.size || 0),
          createdBy: 'gaelic-coach-ai'
        }
      }
    })

    const [readUrl] = await file.getSignedUrl({
      version: 'v4',
      action: 'read',
      expires: Date.now() + 1000 * 60 * 60 * 24
    })

    return NextResponse.json({
      uploadUrl,
      readUrl,
      gsUri: `gs://${bucketName}/${objectName}`,
      bucket: bucketName,
      objectName,
      maxRecommendedSizeGb: 3
    })
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Unable to create upload URL.' },
      { status: 500 }
    )
  }
}
