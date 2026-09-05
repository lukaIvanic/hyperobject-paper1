# The sensitivity analysis — what does a score actually mean?

This folder documents the model-free metric study, one file per family of
degradations. In the experiment plan (`notes/03-experiments.md`) the families
carry the labels M1–M9; here they go by name.

| file | family | plan label |
|---|---|---|
| [01-dropped-pixels.md](01-dropped-pixels.md) | dropped pixels and pooling | M1 |
| [02-dropped-bands.md](02-dropped-bands.md) | dropped wavelength bands | M2 |
| [03-low-rank-spectra.md](03-low-rank-spectra.md) | low-rank spectra (principal components) | M3 |
| [04-added-noise.md](04-added-noise.md) | added noise | M4 |
| [05-smoothing.md](05-smoothing.md) | spatial smoothing | M5 |
| [06-destriping.md](06-destriping.md) | destriping | M6 |
| [07-gain-error.md](07-gain-error.md) | gain (brightness) error | M7 |
| [08-zero-clamping.md](08-zero-clamping.md) | zero-clamping and flooring | M8 |
| [09-constant-cubes.md](09-constant-cubes.md) | constant cubes (the floor) | M9 |

## The idea, simply

Imagine a teacher who grades a drawing by holding it against the original
and giving a number from 0 to 1. Before trusting the number, you would want
to know how the teacher grades: does a tiny smudge cost a little or a lot?
Does she care more about colours, about shapes, or about brightness? Is a
copy that is *cleaner* than the original punished?

We cannot ask the teacher, but we can hand her drawings we made ourselves.
We take the true answer (the ground-truth hyperspectral cube), damage it in a
way we fully understand and can dial from "barely there" to "severe", and
ask the scorer to grade the damaged copy against the original. Because we
know exactly what is wrong, the score tells us what the scorer thinks of
*that kind and that amount* of error. Doing this for nine kinds of damage
gives a ruler: for any score, ours or a leaderboard's, we can say "this is
about as good as a perfect answer with 1 % of noise on it".

No model is trained anywhere in this study. Everything is computed from the
12 validation images of our split, in 12 seconds.

## What a hyperspectral cube is, and what the scorer looks at

Every image here is a stack of 61 grey pictures, one per wavelength from
400 nm (violet) to 1000 nm (near infrared) in 10 nm steps. A pixel is
therefore not one colour but a *spectrum*: 61 numbers that say how much
light of each wavelength the surface reflects. The scorer compares the
predicted cube with the true one with six measurements:

- **SAM** (spectral angle, in degrees): treats the two spectra at a pixel as
  arrows in 61-dimensional space and measures the angle between them. It
  only cares about the *shape* of the spectrum, not how bright it is.
  Averaged over pixels.
- **SID** (spectral information divergence): normalises each spectrum so
  that it sums to one, then measures how different the two "distributions"
  are with logarithms. Also shape only, and very sensitive whenever a value
  is near zero, because a logarithm of a tiny number is a huge number.
  Averaged over pixels.
- **ERGAS** (relative band error): for each of the 61 bands, the root-mean-
  square error divided by the band's mean value, combined into one number
  (×100). This one *does* care about brightness and scale.
- **PSNR** and **SSIM**: both cubes are first turned into an ordinary colour
  photo (an sRGB render with a standard daylight illuminant), and the two
  photos are compared the way image-quality papers do: PSNR is a decibel
  version of the pixel error, SSIM is a "structural similarity" between 0
  and 1 that looks at local contrast and texture.
- **ΔE00** (colour difference): the same two photos compared with the
  perceptual colour-difference formula of the CIE; roughly, 1 unit is a
  just-noticeable difference to a human.

Each measurement is turned into a sub-score between 0 and 1 by the rule
S = exp(−x/τ), with a "tolerance" τ per metric: 5° for SAM, 0.02 for SID,
3 for ERGAS, 3 for ΔE00. So a SAM of 5° gives 0.37, of 10° gives 0.14, of
15° gives 0.05. PSNR is scaled linearly from 20 dB (score 0) to 50 dB
(score 1); SSIM is used as it is. Then

    S_spec = (S_SAM · S_SID · S_ERGAS)^(1/3)        the spectral part
    S_spat = (S_PSNR + SSIM) / 2                    the spatial part
    S_col  = S_ΔE00                                 the colour part
    SSC    = S_spec^0.5 · S_spat^0.35 · S_col^0.15  the composite

Two consequences drive everything in this study. First, the composite is a
*product*: one bad factor drags the whole score down no matter how good the
others are, and the spectral part alone carries half the exponent. Second,
each sub-score is *exponential* in the metric: the first few degrees of SAM
or the first hundredths of SID cost the most, so small errors are punished
hardest, and the score saturates near zero long before the error is severe.
(Every sub-score is also clipped at a minimum of 1e-6, which is why the
worst possible SSC is not exactly 0.)

The formula was recovered from the organisers' compiled bytecode; our GPU
implementation (`src/score.py`) matches their numpy reference to 1e-4 on
every component. How the leaderboard *deploys* it on Kaggle is a separate
question — see the constant-cubes file.

## Regions

Every image in this dataset is the same scene: an object standing on a
white paper sheet, on a dark table rail with a clamp, in front of a
background. We score every degraded cube four times:

- **full** — the whole 1024 × 1024 frame, the way the leaderboard does it;
- **object** — the object together with the paper sheet it stands on (1–75 %
  of the frame depending on the object);
- **table** — the dark rail and clamp below the sheet (4–8 % of the frame);
- **background** — everything else.

The region masks were built from the ground truth and audited image by image
(`src/make_regions.py`, `data/masks/`). Per region, the pixel-wise metrics
(SAM, SID, ΔE00, SSIM) are averaged over that region's pixels only, PSNR uses
the region's mean squared error, and ERGAS uses per-band errors and means
over the region's pixels.

## How to read the figures in each file

Each family has an **example** figure and a **results** figure.

The example figure shows one validation image (`Category-2_a_0013`, a book
spine on the sheet) at a mild and at a strong setting. From left to right:
the ground truth rendered as a colour photo (brightened for display), the
degraded cube rendered the same way, a map of the mean absolute difference
per pixel on a logarithmic colour scale (black = untouched, yellow = large),
and the spectra at three marked pixels — orange on the object, green on the
table rail, red on the background — solid for the truth, dashed for the
degraded copy. Notice in every spectrum plot how *small* the table pixel's
reflectance is (about 0.002 across all bands, against 0.05–0.10 on the
object): that single fact explains most of what follows.

The results figure has one panel per metric, plus the composite and its
three factors, against the setting; one line per region; every point is the
mean over the 12 validation images. The tables in the text carry the same
numbers.

## The ruler, in one table

Composite score SSC of a *perfect prediction with only the named defect*,
mean over the 12 validation images, object region and full frame:

| defect | object | full frame |
|---|---|---|
| 1 pixel in 100 refilled from its neighbours | 0.98 | 0.97 |
| 2× pooling (half the resolution) | 0.67 | 0.50 |
| 8× pooling | 0.21 | 0.13 |
| every 2nd wavelength band interpolated | 0.71 | 0.39 |
| spectra rebuilt from 12 principal components (99.93 % of variance) | 0.71 | 0.48 |
| spectra rebuilt from 4 principal components (99.27 % of variance) | 0.27 | 0.02 |
| Gaussian noise σ = 0.001 (0.1 % reflectance) | 0.97 | 0.86 |
| Gaussian noise σ = 0.003 | 0.90 | 0.41 |
| Gaussian noise σ = 0.01 | 0.66 | 0.04 |
| Gaussian blur σ = 0.5 px | 0.90 | 0.82 |
| Gaussian blur σ = 1 px | 0.68 | 0.52 |
| the dataset's static stripe pattern removed | 0.84 | 0.47 |
| everything 3 % too bright (or too dark) | 0.75 | 0.72 |
| everything 10 % too bright | 0.40 | 0.33 |
| values below 0.01 set to exactly 0 | 1.00 | 0.08 |
| values below 0.005 lifted to 0.005 | 1.00 | 0.91 |
| a constant cube (zeros, the mean spectrum, ones) | 0.00 | 0.00 |

## What the study says, in five sentences

1. **The dark pixels own the full-frame score.** The table rail reflects
   almost nothing, so any error there is a huge *relative* error, and SAM
   and SID measure relative shape. Noise of 0.3 % reflectance is nearly
   invisible on the object (0.90) and halves the full-frame score (0.41).
2. **Exact zeros are a trap.** SID's logarithm explodes on a zero, so a
   prediction that outputs exact zeros in the dark regions loses almost
   everything (0.08 full frame) while being perfect on the object. Lifting
   small values to a floor costs nothing. This is the key for reading the
   clamp ablation.
3. **The stripes are part of the score.** The ground truth carries a fixed
   vertical stripe pattern that is the same in every image. A perfect
   prediction *without* it scores 0.84 on the object and 0.47 full frame.
4. **Brightness scale is judged by ERGAS alone.** A 3 % exposure error leaves
   SAM and SID at zero and still costs a quarter of the score.
5. **Constant cubes score zero here but 0.14 on Kaggle.** The leaderboard's
   deployment of the formula differs from the formula at the floor; absolute
   leaderboard numbers near the bottom are not comparable to local ones.

## Reproducing

```bash
python src/score.py            # parity check of the GPU scorer against the numpy reference
python src/metric_study.py     # the study: logs/metric_study*.csv, figs/metric_study.png (12 s)
python src/metric_study_figs.py  # the figures in this folder
```
