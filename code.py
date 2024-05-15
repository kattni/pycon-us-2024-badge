import gc
import random
import time
import board
import displayio
import vectorio
import keypad
import socketpool
import wifi
import terminalio
from adafruit_display_text import bitmap_label as label
import neopixel

from adafruit_led_animation.sequence import AnimationSequence
from adafruit_led_animation.animation.rainbow import Rainbow
from adafruit_led_animation.animation.rainbowchase import RainbowChase
from adafruit_led_animation.animation.rainbowcomet import RainbowComet
from adafruit_led_animation.animation.rainbowsparkle import RainbowSparkle
from adafruit_led_animation.color import WHITE, BLACK

import foamyguy_nvm_helper as nvm_helper
from adafruit_httpserver import Server, Route, as_route, Request, Response, FileResponse, GET, POST

pool = socketpool.SocketPool(wifi.radio)
server = Server(pool, "/static", debug=True)

STATE_BADGE = 0
STATE_TIC_TAC_TOE = 1
STATE_TIC_TAC_TOE_GAMEOVER = 2

CURRENT_STATE = STATE_BADGE

# Ignore multiple state changes if they occur within this many seconds
CHANGE_STATE_BTN_COOLDOWN = 0.75
LAST_STATE_CHANGE = -1

# Button numbers
BUTTON_UP = 0
BUTTON_DOWN = 1
BUTTON_A = 2
BUTTON_B = 3
BUTTON_C = 4

# NeoPixel and Animations setup
pixels = neopixel.NeoPixel(board.SDA, 8)
rainbow = Rainbow(pixels, speed=0.1, period=2)
rainbow_comet = RainbowComet(pixels, speed=0.1, tail_length=11, bounce=True)
rainbow_sparkle = RainbowSparkle(pixels, speed=0.1, num_sparkles=5)
rainbow_chase = RainbowChase(pixels, speed=0.1, size=5, spacing=3)
animations = AnimationSequence(
    rainbow_comet, rainbow, rainbow_sparkle, rainbow_chase, advance_interval=45,
)

# display setup
display = board.DISPLAY
tictactoe_group = displayio.Group()

# background color palette
background_p = displayio.Palette(1)
background_p[0] = 0xffffff

print(f"width: {display.width}")
# make a rectangle same size as display and add it to main group
background_rect = vectorio.Rectangle(pixel_shader=background_p, width=display.width + 1, height=display.height, x=0,
                                     y=0)
tictactoe_group.append(background_rect)

session_score = {"X": 0, "O": 0}


class TicTacToeGame(displayio.Group):
    """
    Helper class to hold the visual and logical elements that make up the game.
    """

    def __init__(self, display):
        super().__init__()
        self.display = display

        # board lines color palette
        self.lines_p = displayio.Palette(1)
        self.lines_p[0] = 0x000000

        # randomly decide who is first.
        self.turn = random.choice(("X", "O"))

        # board lines
        self.left_line = vectorio.Rectangle(pixel_shader=self.lines_p, width=2, height=118, y=5, x=40)
        self.append(self.left_line)
        self.right_line = vectorio.Rectangle(pixel_shader=self.lines_p, width=2, height=118, y=5, x=80)
        self.append(self.right_line)
        self.top_line = vectorio.Rectangle(pixel_shader=self.lines_p, width=118, height=2, y=40, x=5)
        self.append(self.top_line)
        self.bottom_line = vectorio.Rectangle(pixel_shader=self.lines_p, width=118, height=2, y=80, x=5)
        self.append(self.bottom_line)

        #  dotted line box selector indicator
        self.selector_bmp = displayio.OnDiskBitmap("selector.bmp")
        self.selector_tg = displayio.TileGrid(pixel_shader=self.selector_bmp.pixel_shader, bitmap=self.selector_bmp)
        self.append(self.selector_tg)

        # X and O piece bmps
        self.x_bmp = displayio.OnDiskBitmap("x.bmp")
        self.o_bmp = displayio.OnDiskBitmap("o.bmp")

        # mapping of board position indexes to pixel locations
        self.selector_location_map = [
            [(7, 7), (45, 7), (85, 7)],
            [(7, 45), (45, 45), (85, 45)],
            [(7, 85), (45, 85), (85, 85)],
        ]

        # set starting position of the selector
        self.selector_position = [random.randint(0, 2), random.randint(0, 2)]

        # move the selector tilegrid to the starting position, but do not refresh yet
        self.place_tilegrid_at_board_position(self.selector_position, self.selector_tg, refresh=False)

        # list that will hold all X and O piece TileGrids, added as they get played.
        self.played_pieces = []

        # 2D list representation of the board state
        self.board_state = [
            ["", "", ""],
            ["", "", ""],
            ["", "", ""],
        ]

        self.winner_line_polygon = None
        self.winner_line_palette = displayio.Palette(1)
        self.winner_line_palette[0] = 0x000000

        self.winner_line_map = {
            "row-0": ((12, 17), (12, 23), (115, 23), (115, 17)),
            "row-1": ((12, 57), (12, 63), (115, 63), (115, 57)),
            "row-2": ((12, 97), (12, 103), (115, 103), (115, 97)),
            "col-0": ((20, 12), (26, 12), (26, 115), (20, 115)),
            "col-1": ((58, 12), (64, 12), (64, 115), (58, 115)),
            "col-2": ((98, 12), (104, 12), (104, 115), (98, 115)),
            "diag-tld": ((5, 15), (15, 5), (115, 105), (105, 115)),
            "diag-bru": ((5, 105), (15, 115), (115, 15), (105, 5)),
        }

    def reset_game(self):
        while len(self.played_pieces) > 0:
            self.remove(self.played_pieces.pop())
        for row_idx in range(3):
            for col_idx in range(3):
                self.board_state[row_idx][col_idx] = ""

        print("board state after reset")
        print(self.board_state)
        # set starting position of the selector
        self.selector_position = [random.randint(0, 2), random.randint(0, 2)]

        # move the selector tilegrid to the starting position, but do not refresh yet
        self.place_tilegrid_at_board_position(self.selector_position, self.selector_tg, refresh=False)

        print(f"inside reset_game() winner line is: {self.winner_line_polygon}")
        if self.winner_line_polygon is not None:
            self.remove(self.winner_line_polygon)

    def move_selector_up(self):
        if self.selector_position[1] > 0:
            self.selector_position[1] -= 1
            self.place_tilegrid_at_board_position(self.selector_position, self.selector_tg)

    def move_selector_down(self):
        if self.selector_position[1] < 2:
            self.selector_position[1] += 1
            self.place_tilegrid_at_board_position(self.selector_position, self.selector_tg)

    def move_selector_left(self):
        if self.selector_position[0] > 0:
            self.selector_position[0] -= 1
            self.place_tilegrid_at_board_position(self.selector_position, self.selector_tg)

    def move_selector_right(self):
        if self.selector_position[0] < 2:
            self.selector_position[0] += 1
            self.place_tilegrid_at_board_position(self.selector_position, self.selector_tg)

    def play_piece_at(self, piece, position, refresh=False):
        # create the right type of TileGrid based on turn
        if piece == "X":
            piece_tg = displayio.TileGrid(pixel_shader=self.x_bmp.pixel_shader, bitmap=self.x_bmp)
        else:  # O's turn
            piece_tg = displayio.TileGrid(pixel_shader=self.o_bmp.pixel_shader, bitmap=self.o_bmp)

        # append it to self Group instance
        self.append(piece_tg)

        # append it to pieces list so we can remove it later
        self.played_pieces.append(piece_tg)

        # move piece TileGrid to the current selected position, but do not refresh
        # unless refresh arg was True
        self.place_tilegrid_at_board_position(position, piece_tg, refresh=refresh)

        # update the board state with this move
        self.board_state[self.selector_position[1]][self.selector_position[0]] = piece

    def play_current_move(self):
        """
        Place a piece at the selected position based on which turn it is currently.
        """

        self.play_piece_at(self.turn, self.selector_position, refresh=False)

        # set the turn to next players
        self.turn = "X" if self.turn == "O" else "O"

        # print the board state for debugging
        for row in self.board_state:
            print(row)

        try:
            # update selector_position to a random empty location
            self.selector_position = random.choice(self.empty_spots)
        except IndexError:
            # no more empty spaces
            pass

        # move the selector TileGrid to the selector_position and refresh
        self.place_tilegrid_at_board_position(self.selector_position, self.selector_tg, refresh=False)

    def check_winner(self):
        winner = None
        # horizontals:
        for row_idx, row in enumerate(self.board_state):
            if row.count(row[0]) == 3 and row[0] != "":
                winner = row[0]
                return winner, f"row-{row_idx}"
        # verticals
        for col_idx in range(len(self.board_state)):
            col = []
            for row in self.board_state:
                col.append(row[col_idx])

            if col.count(col[0]) == 3 and col[0] != "":
                winner = col[0]
                return winner, f"col-{col_idx}"
        # diagonals
        top_left_down = []
        bottom_right_up = []

        for i in range(3):
            top_left_down.append(self.board_state[i][i])
            bottom_right_up.append(self.board_state[2 - i][i])

        if top_left_down.count(top_left_down[0]) == 3 and top_left_down[0] != "":
            winner = top_left_down[0]
            return winner, f"diag-tld"

        if bottom_right_up.count(bottom_right_up[0]) == 3 and bottom_right_up[0] != "":
            winner = bottom_right_up[0]
            return winner, f"diag-bru"

        return None

    def show_winner_line(self, line_type):
        if self.winner_line_polygon is None:
            self.winner_line_polygon = vectorio.Polygon(pixel_shader=self.winner_line_palette,
                                                        points=list(self.winner_line_map[line_type]), x=0, y=0)
            self.append(self.winner_line_polygon)
        else:
            self.winner_line_polygon.points = list(self.winner_line_map[line_type])
            self.append(self.winner_line_polygon)

    @property
    def empty_spots(self):
        """
        returns a list of empty board positions
        """
        empty_spots = []
        for row in range(3):
            for col in range(3):

                if self.board_state[col][row] == "":
                    empty_spots.append([row, col])
        return empty_spots

    def place_tilegrid_at_board_position(self, board_position, tilegrid, refresh=True):
        """
        place a tilegrid at a specified board_position. Optionally refresh the display afterward.
        """
        if 0 <= board_position[0] <= 2 and 0 <= board_position[1] <= 2:
            tilegrid.x, tilegrid.y = self.selector_location_map[board_position[1]][board_position[0]]
            if refresh:
                self.display.refresh()
        else:
            print(f"position: {board_position} is out of bounds")


# create the game instance
game = TicTacToeGame(display)

# add it to main group
tictactoe_group.append(game)

# button keys setup
buttons = keypad.Keys((board.SW_UP, board.SW_DOWN, board.SW_A, board.SW_B, board.SW_C), value_when_pressed=True)
pressed_buttons = []

badge_group = displayio.Group()

badge_odb = displayio.OnDiskBitmap("badge.BMP")
badge_tg = displayio.TileGrid(bitmap=badge_odb, pixel_shader=badge_odb.pixel_shader)
badge_group.append(badge_tg)

SESSION_SCORE_TEMPLATE_STR = "Score\nRound:\n X: {}\n O: {}"
session_score_text = label.Label(terminalio.FONT,
                                 text=SESSION_SCORE_TEMPLATE_STR.format(session_score["X"], session_score["O"]),
                                 color=BLACK, scale=2, line_spacing=1.1)

session_score_text.anchor_point = (0, 0)
session_score_text.anchored_position = (134, 2)
tictactoe_group.append(session_score_text)

all_time_score = None
try:
    all_time_score = nvm_helper.read_data()
except EOFError:
    # No data in NVM
    all_time_score = {"X": 0, "O": 0}
    nvm_helper.save_data(all_time_score, test_run=False)

ALL_SCORE_TEMPLATE_STR = "\nAll:\n X: {}\n O: {}"
all_score_text = label.Label(terminalio.FONT,
                             text=ALL_SCORE_TEMPLATE_STR.format(all_time_score["X"], all_time_score["O"]),
                             color=BLACK, scale=2, line_spacing=1.1)

all_score_text.anchor_point = (1.0, 0)
all_score_text.anchored_position = (display.width - 2, 2)
tictactoe_group.append(all_score_text)

if wifi.radio.ipv4_address:
    ip_text = label.Label(terminalio.FONT,
                          text=f"IP: {str(wifi.radio.ipv4_address)}",
                          color=BLACK)
    ip_text.anchor_point = (1.0, 1.0)
    ip_text.anchored_position = (display.width-2, display.height-2)
    tictactoe_group.append(ip_text)

def set_state(new_state):
    if new_state == STATE_BADGE:
        display.root_group = badge_group
    elif new_state == STATE_TIC_TAC_TOE:
        display.root_group = tictactoe_group
    try:
        display.refresh()
    except RuntimeError as e:
        print("Caught Runtime error, probably refreshed too soon.")
        print(e)
        time.sleep(display.time_to_refresh + 0.6)
        display.refresh()


set_state(CURRENT_STATE)
pixel_brightness_base_value = 0
brightness = 0.2


def pixel_brightness():
    global pixel_brightness_base_value
    pixel_brightness_current_value = ((pixel_brightness_base_value % 10) / 10) + 0.2
    pixel_brightness_base_value += 2
    print(pixel_brightness_current_value)
    return pixel_brightness_current_value


INDEX_TEMPLATE = None
with open("static/index.html", "r") as f:
    INDEX_TEMPLATE = f.read()

COLOR_PICKER_TEMPLATE = None
with open("static/color_picker.html", "r") as f:
    COLOR_PICKER_TEMPLATE = f.read()


@server.route("/", (GET, POST))
def index_handler(request: Request):
    if request.method == GET:

        hex_rgb = request.query_params.get("neopixel_color")
        if hex_rgb is not None:
            hex_rgb = hex_rgb.replace("%23", "0x")
            # print(f"hex rgb: {hex(int(hex_rgb, 16))}")
            pixels.brightness = brightness
            animations.freeze()
            animations.fill(int(hex_rgb, 16))
        else:
            hex_rgb = ""

    return Response(request, INDEX_TEMPLATE.format(hex_rgb.replace("0x", "#"),
                                                   all_time_score['X'],
                                                   all_time_score['O']), content_type="text/html")

print(str(wifi.radio.ipv4_address))
server.start()

while True:
    server.poll()
    event = buttons.events.get()
    if event:
        if event.pressed:
            if event.key_number not in pressed_buttons:
                pressed_buttons.append(event.key_number)
        elif event.released:
            if event.key_number in pressed_buttons:
                pressed_buttons.remove(event.key_number)
    try:
        if CURRENT_STATE == STATE_TIC_TAC_TOE:
            animations.freeze()
            animations.fill(BLACK)
            if event:
                print(event)

                if BUTTON_A in pressed_buttons and \
                        event.key_number == BUTTON_C and event.released:
                    print("A held and C pressed")
                    session_score["X"] = 0
                    session_score["O"] = 0
                    CURRENT_STATE = STATE_BADGE
                    set_state(CURRENT_STATE)
                    LAST_STATE_CHANGE = time.monotonic()
                    continue

                if event.key_number == 0 and event.released:
                    game.move_selector_up()
                elif event.key_number == 1 and event.released:
                    game.move_selector_down()
                elif event.key_number == 2 and event.released:
                    game.move_selector_left()
                elif event.key_number == 4 and event.released:
                    game.move_selector_right()
                elif event.key_number == 3 and event.released:

                    if game.board_state[game.selector_position[1]][game.selector_position[0]] == "":
                        game.play_current_move()
                        winner = game.check_winner()
                        if winner:
                            print("WINNER:")
                            print(winner)
                            session_score[winner[0]] += 1
                            all_time_score[winner[0]] += 1
                            nvm_helper.save_data(all_time_score, test_run=False)

                            game.show_winner_line(winner[1])
                            CURRENT_STATE = STATE_TIC_TAC_TOE_GAMEOVER
                            session_score_text.text = SESSION_SCORE_TEMPLATE_STR.format(session_score["X"],
                                                                                        session_score["O"])
                            all_score_text.text = ALL_SCORE_TEMPLATE_STR.format(all_time_score["X"],
                                                                                all_time_score["O"])
                            display.refresh()
                            continue
                        else:
                            display.refresh()
                    else:
                        print("Can't play at an occupied space.")
        elif CURRENT_STATE == STATE_TIC_TAC_TOE_GAMEOVER:
            if event:
                if event.released:
                    game.reset_game()
                    CURRENT_STATE = STATE_TIC_TAC_TOE
                    display.refresh()
                    continue
        elif CURRENT_STATE == STATE_BADGE:
            animations.animate()
            if event:
                if event.key_number == BUTTON_UP and event.released:
                    print(f"free mem: {gc.mem_free()}")
                    animations.resume()
                    animations.next()
                if event.key_number == BUTTON_DOWN and event.released:
                    animations.resume()
                    animations.previous()
                if event.key_number == BUTTON_B and event.released:
                    animations.freeze()
                    animations.fill(BLACK)
                if event.key_number == BUTTON_C and event.released:
                    brightness = pixel_brightness()
                    pixels.brightness = brightness
                if LAST_STATE_CHANGE + CHANGE_STATE_BTN_COOLDOWN < time.monotonic():
                    print(f"badged state event: {event}")
                    if BUTTON_A in pressed_buttons and \
                            event.key_number == BUTTON_C and event.released:
                        print("A held and C pressed")
                        CURRENT_STATE = STATE_TIC_TAC_TOE
                        session_score_text.text = SESSION_SCORE_TEMPLATE_STR.format(session_score["X"],
                                                                                    session_score["O"])
                        set_state(CURRENT_STATE)
                        for _element in game:
                            print(type(_element))
                            print(_element)

    except RuntimeError as e:
        print("Caught Runtime error, probably refreshed too soon.")
        print(e)
        time.sleep(display.time_to_refresh + 0.6)
        display.refresh()
