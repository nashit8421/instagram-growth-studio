#!/bin/sh
# Demo with 10 sample sounds in a throwaway data dir. Never touches ~/.claude.
# Sample names are made up. They are not real trending data.
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)
export IG_DATA_DIR=$(mktemp -d)
A="python3 $HERE/audio.py"
T=--today=2026-10-15

$A add $T --seen 2026-10-08 --name "Golden Hour Loop" --artist "Mira K" --source instagram --region IN --reels-count 2.1K --bpm 104 --mood upbeat --business-ok no
$A add $T --seen 2026-10-14 --name "Golden Hour Loop" --artist "Mira K" --source instagram --region IN --reels-count 9.8K
$A add $T --seen 2026-10-13 --name "Quiet Office" --artist "Lo Studio" --source instagram --region IN --reels-count 4K --trend rising --bpm 82 --mood lofi --business-ok yes
$A add $T --seen 2026-10-12 --name "Bassline Theory" --artist "DJ Arun" --source instagram --region IN --reels-count 38K --trend peaking --bpm 124 --mood upbeat --business-ok unknown
$A add $T --seen 2026-09-20 --name "Old Hit Remix" --artist "Various" --source instagram --region IN --reels-count 410K --trend fading --bpm 128 --mood upbeat --business-ok no
$A add $T --seen 2026-10-14 --name "Monsoon Strings" --artist "Tara Sen" --source tiktok --region IN --reels-count 60K --trend rising --bpm 96 --mood emotional --business-ok unknown
$A add $T --seen 2026-10-10 --name "Tiny Victory" --artist "Meta Sound Collection" --source instagram --region IN --reels-count 1.5K --trend rising --bpm 110 --mood upbeat --business-ok yes
$A add $T --seen 2026-10-11 --name "Cinematic Rise" --artist "Hollow" --source instagram --region US --reels-count 22K --trend rising --bpm 140 --mood dramatic --business-ok yes
$A add $T --seen 2026-10-14 --name "Oops Sting" --artist "Funny Bones" --source instagram --region IN --reels-count 180 --trend rising --bpm 118 --mood funny --business-ok yes
$A add $T --seen 2026-09-01 --name "Summer Ends" --artist "Kavi" --source instagram --region IN --reels-count 75K --trend peaking --bpm 100 --mood calm --business-ok yes
$A add $T --seen 2026-10-09 --name "Desk Beat" --artist "Lo Studio" --source other --region IN --bpm 90 --mood lofi --business-ok yes

echo; $A list $T
echo; echo '### creator, music-led, upbeat'
$A suggest $T --reel-length 28 --mood upbeat --account creator --region IN --top 3
echo; echo '### business, voiceover, with script'
$A suggest $T --reel-length 28 --mood upbeat --account business --voiceover yes --script "$HERE/examples/demo_script.txt" --region IN --top 3
echo; $A prune $T --older-than 28
rm -rf "$IG_DATA_DIR"
