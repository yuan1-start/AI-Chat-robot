cmake_minimum_required(VERSION 3.0.2)
project(spark_chat)

find_package(catkin REQUIRED COMPONENTS
  rospy
  std_msgs
)

catkin_package(
  CATKIN_DEPENDS rospy std_msgs
)

install(DIRECTORY config launch
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}
)

install(FILES scripts/asr_worker.py
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}/scripts
)

catkin_install_python(PROGRAMS
  scripts/asr_node.py
  scripts/baidu_tts_node.py
  scripts/chat_node.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)