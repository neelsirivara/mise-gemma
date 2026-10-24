// Camera preview + snapshots. Phones default to the back camera, pointed at the counter.
const isPhone = matchMedia("(pointer: coarse)").matches;

export async function startCamera(video, { deviceId } = {}) {
  const want = deviceId ? { deviceId: { exact: deviceId }, width: 1280, height: 720 }
    : isPhone ? { facingMode: { ideal: "environment" }, width: 1280, height: 720 } : { width: 1280, height: 720 };
  const stream = await navigator.mediaDevices.getUserMedia({ video: want, audio: false })
    .catch(() => navigator.mediaDevices.getUserMedia({ video: true, audio: false }));
  stopCamera(video);
  video.srcObject = stream;
  await video.play().catch(() => {});
  return stream;
}

export function stopCamera(video) {
  if (video?.srcObject) video.srcObject.getTracks().forEach((t) => t.stop());
  if (video) video.srcObject = null;
}

export function snapshot(video, maxW = 1024) {
  if (!video?.videoWidth) return Promise.resolve(null);
  const scale = Math.min(1, maxW / video.videoWidth);
  const c = document.createElement("canvas");
  c.width = Math.round(video.videoWidth * scale);
  c.height = Math.round(video.videoHeight * scale);
  c.getContext("2d").drawImage(video, 0, 0, c.width, c.height);
  return new Promise((r) => c.toBlob(r, "image/jpeg", 0.85));
}

// Downscale a picked photo (phone photos are 4000px+; the model sees ~1000px anyway)
export async function shrink(file, maxW = 1280) {
  const bmp = await createImageBitmap(file);
  const scale = Math.min(1, maxW / bmp.width);
  const c = document.createElement("canvas");
  c.width = Math.round(bmp.width * scale);
  c.height = Math.round(bmp.height * scale);
  c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
  return new Promise((r) => c.toBlob(r, "image/jpeg", 0.85));
}
