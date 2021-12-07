import os
import re
import qt_gui.plugin
import python_qt_binding

# ROS version specific imports
from .constants import _MICROSTRAIN_ROS_VERISON
if _MICROSTRAIN_ROS_VERISON == 1:
  import rospy
  import tf.transformations
elif _MICROSTRAIN_ROS_VERISON == 2:
  import rclpy
  import rclpy.exceptions
  import rclpy.time
  import rclpy.timer
  from rclpy.callback_groups import ReentrantCallbackGroup
  import transforms3d.euler

from .constants import _PACKAGE_RESOURCE_DIR
from .constants import _NODE_NAME_ENV_KEY, _DEFAULT_NODE_NAME
from .constants import _DEFAULT_MESSAGE_TIMEOUT, _DEFAULT_POLL_INTERVAL, _DEFAULT_VAL, _DEFAULT_STR
from .constants import _ICON_GREY_UNCHECKED_SMALL, _ICON_GREEN_UNCHECKED_SMALL

class MicrostrainServices:
  
  def __init__(self, node, node_name):
    # Save the node name to the class so we can use it later
    self._node = node
    self._node_name = node_name

  def call_service(self, service_path, service_type, **kwargs):
    # Determine the service name
    service_name = os.path.join(self._node_name, service_path)

    # Different functionality between ROS 1 and ROS 2
    if _MICROSTRAIN_ROS_VERISON == 1:
      # Call the service, and return the result
      try:
        service_func = rospy.ServiceProxy(service_name, service_type)
        response = service_func(**kwargs)
        if hasattr(response, 'success'):
          if response.success:
            return response
          else:
            return _DEFAULT_VAL
        else:
          return response
      except Exception:
        return _DEFAULT_VAL
    elif _MICROSTRAIN_ROS_VERISON == 2:
      client = self._node.create_client(service_type, service_name)

      # Copy the kwargs into the service request
      req = service_type.Request()
      for key, value in kwargs.items():
        if hasattr(req, key):
          setattr(req, key, value)

      # Call the service and return the result
      try:
        return client.call_async(req)
      except Exception:
        return _DEFAULT_VAL
      

class Monitor(object):

  def __init__(self, node, node_name, path, message_type, message_timeout = _DEFAULT_MESSAGE_TIMEOUT):
    # Set up some common variables
    self._node = node
    self._node_name = node_name
    self._monitor_path = path
    self._last_message_received_time = 0
    self._message_timeout = message_timeout
    self._current_message = message_type()

  def stop(self):
    self._last_message_received_time = 0

  def _ros_time(self):
    if _MICROSTRAIN_ROS_VERISON == 1:
      return rospy.Time.now().to_sec()
    elif _MICROSTRAIN_ROS_VERISON == 2:
      return self._node.get_clock().now().to_msg().sec
    else:
      return 0

  def _euler_from_quaternion(self, quaternion):
    if _MICROSTRAIN_ROS_VERISON == 1:
      return tf.transformations.euler_from_quaternion(quaternion)
    elif _MICROSTRAIN_ROS_VERISON == 2:
      return transforms3d.euler.quat2euler(quaternion)
    else:
      return (0.0, 0.0, 0.0)

  @property
  def _message_timed_out(self):
    time_elapsed_since_last_message = self._ros_time() - self._last_message_received_time
    return time_elapsed_since_last_message > self._message_timeout
  
  def _get_val(self, val, default = _DEFAULT_VAL):
    if self._message_timed_out:
      return default
    else:
      return val
  
  def _get_string(self, val, default_val = _DEFAULT_VAL, default_str = _DEFAULT_STR):
    if val is default_val or self._get_val(val, default_val) is default_val:
      return default_str
    else:
      return str(val)

  def _get_string_units(self, val, units, default_val=_DEFAULT_VAL, default_str=_DEFAULT_STR):
    if val is default_val or self._get_val(val, default_val) is default_val:
      return default_str
    else:
      return "%.6f %s" % (val, units)
  
  def _get_small_boolean_icon_string(self, val, default_val = _DEFAULT_VAL):
    if val is default_val or self._get_val(val, default_val) is default_val:
      return _ICON_GREY_UNCHECKED_SMALL
    else:
      if val:
        return _ICON_GREEN_UNCHECKED_SMALL
      else:
        return _ICON_GREY_UNCHECKED_SMALL


class ServiceMonitor(Monitor):
  
  def __init__(self, node, node_name, path, service_type, message_timeout=_DEFAULT_MESSAGE_TIMEOUT, callback=_DEFAULT_VAL, poll_interval=_DEFAULT_POLL_INTERVAL):
    # Initialize the parent class
    if _MICROSTRAIN_ROS_VERISON == 1:
      super(ServiceMonitor, self).__init__(node, node_name, path, service_type._response_class, message_timeout=message_timeout)
      self._current_response = service_type._response_class()
    elif _MICROSTRAIN_ROS_VERISON == 2:
      super(ServiceMonitor, self).__init__(node, node_name, path, service_type.Response, message_timeout=message_timeout)
      self._current_future = rclpy.Future()
      self._current_future._done = False

    # Save some important information about the services
    self._service_type = service_type

    # Initialize a client that we will use to communicate with the services
    self._microstrain_services = MicrostrainServices(self._node, node_name)

    # Start polling the service in a timer
    if callback is _DEFAULT_VAL:
      callback = self._default_callback

    if _MICROSTRAIN_ROS_VERISON == 1:
      self._poll_timer = rospy.Timer(rospy.Duration(poll_interval), callback)
    elif _MICROSTRAIN_ROS_VERISON == 2:
      self._poll_timer = self._node.create_timer(poll_interval, callback)
  
  def stop(self):
    super(ServiceMonitor, self).stop()
    if _MICROSTRAIN_ROS_VERISON == 1:
      self._poll_timer.shutdown()
    elif _MICROSTRAIN_ROS_VERISON == 2:
      self._poll_timer.destroy()
    del self._poll_timer

  def _default_callback(self, event=None):
    if _MICROSTRAIN_ROS_VERISON == 1:
      # Get the result of the service call
      new_message = self._microstrain_services.call_service(self._monitor_path, self._service_type)

      # If the service returned an actual value, save the time of success
      if new_message is not _DEFAULT_VAL:
        self._current_response = new_message
        self._last_message_received_time = self._ros_time()
    elif _MICROSTRAIN_ROS_VERISON == 2:
      self._current_future = self._microstrain_services.call_service(self._monitor_path, self._service_type)
  
  @property
  def _current_message(self):
    if _MICROSTRAIN_ROS_VERISON == 1:
      return self._current_response
    elif _MICROSTRAIN_ROS_VERISON == 2:
      if self._current_future.done():
        response = self._current_future.result()
        if hasattr(response, 'success'):
          if response.success:
            self._last_message_received_time = self._ros_time()
            return response
          else:
            return self._service_type.Response()
        else:
          self._last_message_received_time = self._ros_time()
          return response
      else:
        return self._service_type.Response()
    else:
      return _DEFAULT_VAL
  
  @_current_message.setter
  def _current_message(self, current_message):
    if _MICROSTRAIN_ROS_VERISON == 1:
      self._current_response = current_message


class SubscriberMonitor(Monitor):

  def __init__(self, node, node_name, path, message_type, message_timeout=_DEFAULT_MESSAGE_TIMEOUT, callback=_DEFAULT_VAL):
    # Initialize the parent class
    super(SubscriberMonitor, self).__init__(node, node_name, path, message_type, message_timeout=message_timeout)

    # Save th topic name
    self._topic = os.path.join(self._node_name, self._monitor_path)

    # Set up the subscriber
    if callback is _DEFAULT_VAL:
      callback = self._default_callback

    if _MICROSTRAIN_ROS_VERISON == 1: 
      self._subscriber = rospy.Subscriber(self._topic, message_type, callback)
    elif _MICROSTRAIN_ROS_VERISON == 2:
      self._subscriber = self._node.create_subscription(message_type, self._topic, callback, 10)

  def stop(self):
    super(SubscriberMonitor, self).stop()
    if _MICROSTRAIN_ROS_VERISON == 1:
      self._subscriber.unregister()
    elif _MICROSTRAIN_ROS_VERISON == 2:
      self._subscriber.destroy()
    del self._subscriber

  def _default_callback(self, message):
    self._current_message = message
    self._last_message_received_time = self._ros_time()
