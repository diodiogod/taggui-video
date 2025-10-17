#!/usr/bin/env python3
import sys
print('=== Starting Video Editor Test ===')
try:
    from taggui.utils.video_editor import VideoEditor
    from pathlib import Path
    import subprocess
    import json
    print('Imports successful')

    if len(sys.argv) < 2:
        print('Usage: python test_video.py <input_video_path>')
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = input_path.parent / f"{input_path.stem}_test{input_path.suffix}"

    print(f'Input exists: {input_path.exists()}')
    print(f'Input size: {input_path.stat().st_size if input_path.exists() else "N/A"}')

    # Get current frames
    probe_cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', str(input_path)]
    probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
    probe_data = json.loads(probe_result.stdout)
    current_frames = int([s for s in probe_data['streams'] if s['codec_type'] == 'video'][0]['nb_frames'])

    print(f'Current frames: {current_frames}')

    # Calculate targets
    current_n = (current_frames - 1) // 4
    lower_target = current_n * 4 + 1
    upper_target = (current_n + 1) * 4 + 1

    print(f'Current N: {current_n}')
    print(f'Lower target: {lower_target} (remove {max(0, current_frames - lower_target)} frames)')
    print(f'Upper target: {upper_target} (add {upper_target - current_frames} frames)')

    frames_to_remove_for_lower = max(0, current_frames - lower_target)
    frames_to_add_for_upper = upper_target - current_frames

    print(f'Frames to remove for lower: {frames_to_remove_for_lower}')
    print(f'Frames to add for upper: {frames_to_add_for_upper}')

    if frames_to_remove_for_lower <= frames_to_add_for_upper:
        final_target = lower_target
        print(f'Chose lower target: {final_target}')
    else:
        final_target = upper_target
        print(f'Chose upper target: {final_target}')

    print(f'Final target: {final_target}')
    print(f'Operation: add {final_target - current_frames} frames')

    print('Testing fix_frame_count_to_n4_plus_1...')
    result = VideoEditor.fix_frame_count_to_n4_plus_1(input_path, output_path, 16.0, True, None)
    print(f'Result: {result}')

    print(f'Output exists: {output_path.exists()}')
    if output_path.exists():
        print(f'Output size: {output_path.stat().st_size}')

        # Check output frames
        probe_cmd2 = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', str(output_path)]
        probe_result2 = subprocess.run(probe_cmd2, capture_output=True, text=True)
        if probe_result2.returncode == 0:
            probe_data2 = json.loads(probe_result2.stdout)
            output_frames = int([s for s in probe_data2['streams'] if s['codec_type'] == 'video'][0]['nb_frames'])
            print(f'Output frames: {output_frames}')
            print(f'Expected: 81')
            print(f'Difference: {output_frames - 81}')
        else:
            print('Failed to probe output')

except Exception as e:
    print(f'ERROR: {e}')
    import traceback
    traceback.print_exc()

print('=== Test Complete ===')