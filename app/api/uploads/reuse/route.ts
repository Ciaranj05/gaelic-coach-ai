import { NextResponse } from 'next/server'
import { Storage } from '@google-cloud/storage'

type ReuseRequest = {
  objectName?: string
  gsUri?: string
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

function parseGsUri(gsUri?: string) {
  if (!gsUri?.startsWith('gs://')) return null
  const withoutPrefix = gsUri.replace('gs://', '')
  const slashIndex = withoutPrefix.indexOf('/')
  if (slashIndex < 0) return null
  return {
    bucket: withoutPrefix.slice(0, slashIndex),
    objectName: withoutPrefix.slice(slashIndex + 1)
  }
}

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as ReuseRequest
    const parsed = parseGsUri(body.gsUri)
    const bucketName = parsed?.bucket || process.env.GCS_UPLOAD_BUCKET
    const objectName = parsed?.objectName || body.objectName

    if (!bucketName) return NextResponse.json({ error: 'GCS_UPLOAD_BUCKET is not configured.' }, { status: 500 })
    if (!objectName) return NextResponse.json({ error: 'objectName or gsUri is required.' }, { status: 400 })

    const storage = getStorageClient()
    const file = storage.bucket(bucketName).file(objectName)
    const [exists] = await file.exists()
    if (!exists) return NextResponse.json({ error: 'Uploaded file was not found in Google Cloud Storage.' }, { status: 404 })

    const [metadata] = await file.getMetadata()
    const [readUrl] = await file.getSignedUrl({
      version: 'v4',
      action: 'read',
      expires: Date.now() + 1000 * 60 * 60 * 24
    })

    return NextResponse.json({
      readUrl,
      gsUri: `gs://${bucketName}/${objectName}`,
      bucket: bucketName,
      objectName,
      size: Number(metadata.size || 0),
      contentType: metadata.contentType || 'video/mp4',
      updated: metadata.updated
    })
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : 'Unable to reuse uploaded file.' }, { status: 500 })
  }
}
