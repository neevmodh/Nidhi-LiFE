// Where households go: the Nidhi app (Expo) on the web and as an Android APK. Set per deployment.
export const APP_URL = process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:8081";
/** The Android APK from EAS; empty until the build exists, and then the landing page offers the web app instead. */
export const APK_URL = process.env.NEXT_PUBLIC_APK_URL ?? "";
/** Public links for anyone looking at the project: the source, the demo film and the API's own docs. */
export const REPO_URL = "https://github.com/neevmodh/Nidhi-LiFE";
export const VIDEO_URL = "https://www.youtube.com/watch?v=1VaBrlXMwpA";
