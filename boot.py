import board

board.ENABLE_DIO.value = True

import digitalio

up_btn = digitalio.DigitalInOut(board.SW_UP)
up_btn.direction = digitalio.Direction.INPUT
up_btn.pull = digitalio.Pull.DOWN

down_btn = digitalio.DigitalInOut(board.SW_DOWN)
down_btn.direction = digitalio.Direction.INPUT
down_btn.pull = digitalio.Pull.DOWN

a_btn = digitalio.DigitalInOut(board.SW_A)
a_btn.direction = digitalio.Direction.INPUT
a_btn.pull = digitalio.Pull.DOWN

if a_btn.value and up_btn.value and down_btn.value:
    print("up, down, a pressed. resetting highscore")
    import foamyguy_nvm_helper as nvm_helper

    all_time_score = {"X": 0, "O": 0}
    nvm_helper.save_data(all_time_score, test_run=False)