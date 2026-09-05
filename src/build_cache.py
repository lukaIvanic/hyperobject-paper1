"""Build the uncompressed .npy cache from the official archive, once.

Reads  /root/data/raw/<split>/hsi_61/<stem>.h5   (gzip HDF5, dataset "cube")
       /root/data/raw/<split>/mosaic/<stem>.npy
Writes /root/data/cache/<split>/cube/<stem>.npy   float32 (1024, 1024, 61), C-contiguous
       /root/data/cache/<split>/mosaic/<stem>.npy  copied unchanged
       /root/data/cache/wavelengths.npy            (61,) float32, identical in every file

The cube is stored in its native HWC order: a C-contiguous (H, W, 61) array
is byte-for-byte a channels-last (61, H, W) tensor, so it pins and uploads
with zero copies. Every written file is read back and compared bit-for-bit
against the HDF5 read. Splits: train (167), test-public (11), test-private
(mosaics only, 4).
"""
import sys, time, shutil
from multiprocessing import Pool
from pathlib import Path
import h5py, numpy as np

RAW = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/data/raw")
CACHE = Path(sys.argv[2] if len(sys.argv) > 2 else "/root/data/cache")
WAVELENGTHS = np.arange(400, 1001, 10, dtype=np.float32)


def convert_cube(h5_path: Path) -> tuple[str, float]:
    t0 = time.time()
    with h5py.File(h5_path, "r") as f:
        cube = f["cube"][...]
        assert np.array_equal(f["wavelengths"][...], WAVELENGTHS), h5_path
    assert cube.shape == (1024, 1024, 61) and cube.dtype == np.float32, (h5_path, cube.shape, cube.dtype)
    cube = np.ascontiguousarray(cube)
    out = CACHE / h5_path.parent.parent.name / "cube" / (h5_path.stem + ".npy")
    out.parent.mkdir(parents=True, exist_ok=True)
    np.save(out, cube)
    back = np.load(out, mmap_mode="r")
    assert back.flags["C_CONTIGUOUS"] and np.array_equal(back, cube), out
    return h5_path.stem, time.time() - t0


def copy_mosaic(npy_path: Path) -> None:
    m = np.load(npy_path)
    assert m.shape == (1024, 1024) and m.dtype == np.float32, (npy_path, m.shape, m.dtype)
    out = CACHE / npy_path.parent.parent.name / "mosaic" / npy_path.name
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(npy_path, out)
    assert np.array_equal(np.load(out), m), out


if __name__ == "__main__":
    t0 = time.time()
    cubes = sorted(RAW.glob("*/hsi_61/*.h5"))
    mosaics = sorted(RAW.glob("*/mosaic/*.npy"))
    assert len(cubes) == 178 and len(mosaics) == 182, (len(cubes), len(mosaics))
    for m in mosaics:
        copy_mosaic(m)
    with Pool(32) as pool:
        per_file = pool.map(convert_cube, cubes, chunksize=1)
    np.save(CACHE / "wavelengths.npy", WAVELENGTHS)
    total_gb = sum(p.stat().st_size for p in CACHE.rglob("*.npy")) / 1e9
    print(f"{len(cubes)} cubes + {len(mosaics)} mosaics -> {CACHE} ({total_gb:.1f} GB) "
          f"in {time.time() - t0:.0f}s wall; {np.mean([s for _, s in per_file]):.1f}s per cube in-worker")
