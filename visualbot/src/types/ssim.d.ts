declare module "ssim.js" {
  interface SsimImage {
    data: Uint8ClampedArray | Uint8Array | Buffer;
    width: number;
    height: number;
  }
  interface SsimOptions {
    windowSize?: number;
    k1?: number;
    k2?: number;
    bitDepth?: number;
    downsample?: "original" | "fast" | false;
    ssim?: "fast" | "original" | "bezkrovny" | "weber";
  }
  interface SsimResult {
    mssim: number;
    performance: number;
    ssim_map?: { data: number[]; width: number; height: number };
  }
  export function ssim(
    img1: SsimImage,
    img2: SsimImage,
    options?: SsimOptions
  ): SsimResult;
  export default ssim;
}
