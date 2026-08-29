"""ESPHome external component: rubiks_solver."""

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.const import CONF_ID
from esphome.components import servo
from esphome.components import text_sensor
from esphome.components import binary_sensor
from esphome.components import sensor

CODEOWNERS = ["@OkhammahkO"]
DEPENDENCIES = ["servo", "api"]
AUTO_LOAD   = ["text_sensor", "binary_sensor", "sensor"]

CONF_STATUS_SENSOR = "status_sensor"
CONF_BELIEVED_HOME_SENSOR = "believed_home_sensor"
CONF_MOVES_REMAINING_SENSOR = "moves_remaining_sensor"

CONF_TOP_SERVO    = "top_servo"
CONF_BOTTOM_SERVO = "bottom_servo"

# Top servo position settings (raw duty 0-1023)
CONF_T_SERVO_FLIP       = "t_servo_flip"
CONF_T_SERVO_OPEN       = "t_servo_open"
CONF_T_SERVO_CLOSE      = "t_servo_close"
CONF_T_SERVO_REL_OFFSET = "t_servo_rel_offset"
# Top servo timing settings (ms)
CONF_T_FLIP_TO_CLOSE_TIME = "t_flip_to_close_time"
CONF_T_CLOSE_TO_FLIP_TIME = "t_close_to_flip_time"
CONF_T_FLIP_OPEN_TIME     = "t_flip_open_time"
CONF_T_OPEN_CLOSE_TIME    = "t_open_close_time"
# Bottom servo position settings (raw duty 0-1023)
CONF_B_SERVO_CCW    = "b_servo_ccw"
CONF_B_HOME         = "b_home"
CONF_B_SERVO_CW     = "b_servo_cw"
CONF_B_EXTRA_SIDES  = "b_extra_sides"
CONF_B_EXTRA_HOME   = "b_extra_home"
# Bottom servo timing settings (ms)
CONF_B_SPIN_TIME    = "b_spin_time"
CONF_B_ROTATE_TIME  = "b_rotate_time"
CONF_B_REL_TIME     = "b_rel_time"

rubiks_solver_ns      = cg.esphome_ns.namespace("rubiks_solver")
RubiksSolverComponent = rubiks_solver_ns.class_("RubiksSolverComponent", cg.Component)

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID():                  cv.declare_id(RubiksSolverComponent),
        cv.Required(CONF_TOP_SERVO):      cv.use_id(servo.Servo),
        cv.Required(CONF_BOTTOM_SERVO):   cv.use_id(servo.Servo),

        # Servo calibration — all optional, defaults match Cubotino_settings.txt
        # Uncomment and override in YAML after physical assembly / calibration.
        cv.Optional(CONF_T_SERVO_FLIP,       default=54):   cv.int_range(min=0, max=1023),
        cv.Optional(CONF_T_SERVO_OPEN,       default=68):   cv.int_range(min=0, max=1023),
        cv.Optional(CONF_T_SERVO_CLOSE,      default=76):   cv.int_range(min=0, max=1023),
        cv.Optional(CONF_T_SERVO_REL_OFFSET, default=0):    cv.int_range(min=0, max=50),
        cv.Optional(CONF_T_FLIP_TO_CLOSE_TIME, default=900):  cv.positive_int,  # ms
        cv.Optional(CONF_T_CLOSE_TO_FLIP_TIME, default=1000): cv.positive_int,  # ms
        cv.Optional(CONF_T_FLIP_OPEN_TIME,     default=800):  cv.positive_int,  # ms
        cv.Optional(CONF_T_OPEN_CLOSE_TIME,    default=300):  cv.positive_int,  # ms

        cv.Optional(CONF_B_SERVO_CCW,    default=51):   cv.int_range(min=0, max=1023),
        cv.Optional(CONF_B_HOME,         default=76):   cv.int_range(min=0, max=1023),
        cv.Optional(CONF_B_SERVO_CW,     default=101):  cv.int_range(min=0, max=1023),
        cv.Optional(CONF_B_EXTRA_SIDES,  default=2):    cv.int_range(min=0, max=20),
        cv.Optional(CONF_B_EXTRA_HOME,   default=3):    cv.int_range(min=0, max=20),
        cv.Optional(CONF_B_SPIN_TIME,    default=1100): cv.positive_int,  # ms
        cv.Optional(CONF_B_ROTATE_TIME,  default=1200): cv.positive_int,  # ms
        cv.Optional(CONF_B_REL_TIME,     default=100):  cv.positive_int,  # ms

        cv.Optional(CONF_STATUS_SENSOR): text_sensor.text_sensor_schema(),
        # Optimistic — tracks the commanded move sequence, not real position feedback
        # (there is none). True only right after a sequence completes at cover-open +
        # bottom-home; false the instant any step is queued. See docs/servo-tuning.md.
        cv.Optional(CONF_BELIEVED_HOME_SENSOR): binary_sensor.binary_sensor_schema(),
        # Robot actions (flip/spin/rotate) remaining in the current solve — counts down
        # from move_count() to 0 as execute_solution() progresses. Only meaningful while
        # SOLVING; stale between solves otherwise. See mark_action_boundary_() in
        # rubiks_solver.cpp for how it's kept in sync with count_moves()'s definition of
        # "one action".
        cv.Optional(CONF_MOVES_REMAINING_SENSOR): sensor.sensor_schema(
            icon="mdi:counter",
            accuracy_decimals=0,
        ),
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)

    top = await cg.get_variable(config[CONF_TOP_SERVO])
    cg.add(var.set_top_servo(top))

    bot = await cg.get_variable(config[CONF_BOTTOM_SERVO])
    cg.add(var.set_bottom_servo(bot))

    # Top servo position settings
    cg.add(var.set_t_servo_flip(config[CONF_T_SERVO_FLIP]))
    cg.add(var.set_t_servo_open(config[CONF_T_SERVO_OPEN]))
    cg.add(var.set_t_servo_close(config[CONF_T_SERVO_CLOSE]))
    cg.add(var.set_t_servo_rel_offset(config[CONF_T_SERVO_REL_OFFSET]))
    # Top servo timing settings
    cg.add(var.set_t_flip_to_close_time(config[CONF_T_FLIP_TO_CLOSE_TIME]))
    cg.add(var.set_t_close_to_flip_time(config[CONF_T_CLOSE_TO_FLIP_TIME]))
    cg.add(var.set_t_flip_open_time(config[CONF_T_FLIP_OPEN_TIME]))
    cg.add(var.set_t_open_close_time(config[CONF_T_OPEN_CLOSE_TIME]))
    # Bottom servo position settings
    cg.add(var.set_b_servo_ccw(config[CONF_B_SERVO_CCW]))
    cg.add(var.set_b_home(config[CONF_B_HOME]))
    cg.add(var.set_b_servo_cw(config[CONF_B_SERVO_CW]))
    cg.add(var.set_b_extra_sides(config[CONF_B_EXTRA_SIDES]))
    cg.add(var.set_b_extra_home(config[CONF_B_EXTRA_HOME]))
    # Bottom servo timing settings
    cg.add(var.set_b_spin_time(config[CONF_B_SPIN_TIME]))
    cg.add(var.set_b_rotate_time(config[CONF_B_ROTATE_TIME]))
    cg.add(var.set_b_rel_time(config[CONF_B_REL_TIME]))

    if CONF_STATUS_SENSOR in config:
        sens = await text_sensor.new_text_sensor(config[CONF_STATUS_SENSOR])
        cg.add(var.set_status_sensor(sens))

    if CONF_BELIEVED_HOME_SENSOR in config:
        home_sens = await binary_sensor.new_binary_sensor(config[CONF_BELIEVED_HOME_SENSOR])
        cg.add(var.set_believed_home_sensor(home_sens))

    if CONF_MOVES_REMAINING_SENSOR in config:
        moves_sens = await sensor.new_sensor(config[CONF_MOVES_REMAINING_SENSOR])
        cg.add(var.set_moves_remaining_sensor(moves_sens))
