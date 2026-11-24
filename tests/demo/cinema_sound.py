"""Music and effects for the Cinema alfa short, synthesized with FFmpeg filters only (CPU, no model, no sample library).
LABEL: synthetic placeholders. The Studio's own «Áudio» app (Stable Audio 3) needs the GPU and is reserved for the T4 pass.
Usage: python tests/demo/cinema_sound.py <out_dir>"""
import subprocess
import sys
from pathlib import Path

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)


def ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], check=True)


def chord(freqs, seconds):
    # each note: two slightly detuned sines + a soft octave, slow 0.13 Hz swell, long attack/release
    voices = "+".join(f"sin(2*PI*{f}*t)+0.8*sin(2*PI*{f * 1.004:.3f}*t)+0.25*sin(2*PI*{2 * f}*t)" for f in freqs)
    env = f"min(1,t/2.5)*min(1,({seconds}-t)/2.5)*(0.8+0.2*sin(2*PI*0.13*t))"
    return f"aevalsrc='0.05*({voices})*{env}|0.05*({voices})*{env}*(0.97+0.03*sin(2*PI*0.21*t))':s=48000:d={seconds}"


# D minor, Bb, F, C, D minor: low and open, nothing that tells the audience what to feel
progression = [(73.42, 110.0, 174.61), (58.27, 116.54, 174.61), (87.31, 130.81, 220.0), (65.41, 130.81, 196.0), (73.42, 110.0, 174.61)]
parts = []
for i, notes in enumerate(progression):
    part = out / f"_chord{i}.wav"
    ff("-f", "lavfi", "-i", chord(notes, 8), "-c:a", "pcm_s16le", part)
    parts.append(part)
inputs = sum((["-i", p] for p in parts), [])
chain = "[0][1]acrossfade=d=2[x1];[x1][2]acrossfade=d=2[x2];[x2][3]acrossfade=d=2[x3];[x3][4]acrossfade=d=2,lowpass=f=1800,aecho=0.8:0.7:60|130:0.25|0.18[m]"
ff(*inputs, "-filter_complex", chain, "-map", "[m]", "-c:a", "pcm_s16le", out / "music-pad.wav")
for p in parts:
    p.unlink()

# sea: brown noise, low-passed, breathing on a 7 s swell; left and right slightly out of phase
ff("-f", "lavfi", "-i", "anoisesrc=c=brown:r=48000:a=0.5:d=62:s=7", "-f", "lavfi", "-i", "anoisesrc=c=brown:r=48000:a=0.5:d=62:s=11",
   "-filter_complex", "[0]lowpass=f=700,volume='0.55+0.45*sin(2*PI*t/7)':eval=frame[l];[1]lowpass=f=650,volume='0.55+0.45*sin(2*PI*t/7+0.9)':eval=frame[r];"
   "[l][r]join=inputs=2:channel_layout=stereo,highpass=f=40[s]", "-map", "[s]", "-c:a", "pcm_s16le", out / "sea.wav")

# foghorn far away: two low sawtooth-ish partials, slow attack, long tail in the echo
ff("-f", "lavfi", "-i", "aevalsrc='(0.5*sin(2*PI*98*t)+0.3*sin(2*PI*196*t+0.4)+0.15*sin(2*PI*294*t))*min(1,t/0.6)*max(0,min(1,(3.2-t)/1.2))':s=48000:d=4",
   "-af", "lowpass=f=500,aecho=0.8:0.6:420|900:0.35|0.2,apad=pad_dur=4,pan=stereo|c0=c0|c1=c0", "-c:a", "pcm_s16le", out / "foghorn.wav")

# street lamp: a relay click, then a faint mains hum that settles
ff("-f", "lavfi", "-i", "anoisesrc=c=white:r=48000:a=0.9:d=0.03", "-f", "lavfi", "-i", "aevalsrc='0.04*(sin(2*PI*50*t)+0.5*sin(2*PI*100*t))*min(1,t/0.4)*max(0,(5-t)/5)':s=48000:d=5",
   "-filter_complex", "[0]highpass=f=1500,afade=t=out:st=0:d=0.03,apad=pad_dur=0.1[c];[c][1]concat=n=2:v=0:a=1,pan=stereo|c0=c0|c1=c0[o]",
   "-map", "[o]", "-c:a", "pcm_s16le", out / "lamp.wav")
print("\n".join(sorted(p.name for p in out.glob("*.wav"))))
