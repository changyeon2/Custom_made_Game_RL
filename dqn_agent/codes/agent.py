import loa_game, os
from keras.layers.convolutional import Conv2D
from keras.layers import Dense, Flatten
from keras.optimizers import RMSprop
from keras.models import Sequential
from skimage.transform import resize
from skimage.color import rgb2gray
from collections import deque
from keras import backend as K
import tensorflow as tf
import numpy as np
import random
import gym

EPISODE_NUM = 1 # for training, set this with other number


class Agent:
    def __init__(self):
        self.render = True # set this True for rendering game
        self.load_model = True # set this True for bring trained h5 file

        # state & action
        self.state_size = (84, 84, 4)
        self.action_size = 4

        # DQN hyperparameters
        self.epsilon = 1.
        self.epsilon_start, self.epsilon_end = 1.0, 0.1
        self.exploration_steps = 10
        self.epsilon_decay_step = (self.epsilon_start - self.epsilon_end) \
                                  / self.exploration_steps
        self.batch_size = 64
        self.train_start = 20000
        self.update_target_rate = 400
        self.discount_factor = 0.99

        # replay memory
        self.memory = deque(maxlen=100000)
        self.no_op_steps = 30

        # model & target model
        self.model = self.build_model()
        self.target_model = self.build_model()
        self.update_target_model()

        self.optimizer = self.optimizer()

        self.sess = tf.compat.v1.InteractiveSession()
        K.set_session(self.sess)

        self.avg_q_max, self.avg_loss = 0, 0
        self.summary_placeholders, self.update_ops, self.summary_op = \
            self.setup_summary()
        self.summary_writer = tf.compat.v1.summary.FileWriter(
            '../summary/loa', self.sess.graph)
        self.sess.run(tf.compat.v1.global_variables_initializer())

        if self.load_model:
            self.model.load_weights("../save_model/loa_trained.h5")

    def optimizer(self):
        a = K.placeholder(shape=(None,), dtype='int32')
        y = K.placeholder(shape=(None,), dtype='float32')

        prediction = self.model.output

        a_one_hot = K.one_hot(a, self.action_size)
        q_value = K.sum(prediction * a_one_hot, axis=1)
        error = K.abs(y - q_value)

        quadratic_part = K.clip(error, 0.0, 1.0)
        linear_part = error - quadratic_part
        loss = K.mean(0.5 * K.square(quadratic_part) + linear_part)

        optimizer = RMSprop(lr=0.00025, epsilon=0.01)
        updates = optimizer.get_updates(self.model.trainable_weights, [], loss)
        train = K.function([self.model.input, a, y], [loss], updates=updates)

        return train

    def build_model(self):
        """
        state_size = list(self.state_size)
        state_size.append(1)
        input = Input(shape=self.state_size)
        reshape = Reshape(state_size)(input)
        conv = TimeDistributed(Conv2D(16, (8, 8), strides=(4, 4), activation='relu', kernel_initializer='he_normal'))(
            reshape)
        conv = TimeDistributed(Conv2D(32, (4, 4), strides=(2, 2), activation='relu', kernel_initializer='he_normal'))(
            conv)
        conv = TimeDistributed(Flatten())(conv)
        lstm = LSTM(512, activation='tanh', kernel_initializer='he_normal')(conv)
        Qvalue = Dense(self.action_size, activation='linear', kernel_initializer='he_normal')(lstm)

        model = Model(inputs=input, outputs=Qvalue)

        이건 pomdp -> 4장의 이미지를 dqn처럼 한번에 보는 것이 아닌 시간 순서대로 보는 것이 맞다는 내용!!

        """

        model = Sequential()
        model.add(Conv2D(32, (8, 8), strides=(4, 4), activation='relu', input_shape=self.state_size))
        model.add(Conv2D(64, (4, 4), strides=(2, 2), activation='relu'))
        model.add(Conv2D(64, (3, 3), strides=(1, 1), activation='relu'))
        model.add(Flatten())
        model.add(Dense(512, activation='relu'))
        model.add(Dense(self.action_size))
        model.summary()

        return model

    def update_target_model(self):
        self.target_model.set_weights(self.model.get_weights())

    def get_action(self, history):
        history = np.float32(history / 255.0)
        if np.random.rand() <= self.epsilon:
            return random.randrange(self.action_size)  # 학습 후 play할 때는 if-else 지우고 else문 안의 statement만 이용하기(max q)!
        else:
            q_value = self.model.predict(history)
        return np.argmax(q_value[0])

    # save sample <s, a, r, s'> to replay memory
    def append_sample(self, history, action, reward, next_history, dead):
        self.memory.append((history, action, reward, next_history, dead))

    # random batch training
    def train_model(self):
        if self.epsilon > self.epsilon_end:
            self.epsilon -= self.epsilon_decay_step

        mini_batch = random.sample(self.memory, self.batch_size)

        history = np.zeros((self.batch_size, self.state_size[0],
                            self.state_size[1], self.state_size[2]))
        next_history = np.zeros((self.batch_size, self.state_size[0],
                                 self.state_size[1], self.state_size[2]))
        target = np.zeros((self.batch_size,))
        action, reward, dead = [], [], []

        for i in range(self.batch_size):
            history[i] = np.float32(mini_batch[i][0] / 255.)
            next_history[i] = np.float32(mini_batch[i][3] / 255.)
            action.append(mini_batch[i][1])
            reward.append(mini_batch[i][2])
            dead.append(mini_batch[i][4])

        target_value = self.target_model.predict(next_history)

        for i in range(self.batch_size):
            if dead[i]:
                target[i] = reward[i]
            else:
                target[i] = reward[i] + self.discount_factor * \
                            np.amax(target_value[i])

        loss = self.optimizer([history, action, target])
        self.avg_loss += loss[0]

    # training info every episode
    def setup_summary(self):
        episode_total_reward = tf.Variable(0.)
        episode_avg_max_q = tf.Variable(0.)
        episode_duration = tf.Variable(0.)
        episode_avg_loss = tf.Variable(0.)

        tf.compat.v1.summary.scalar('Total Reward/Episode', episode_total_reward)
        tf.compat.v1.summary.scalar('Average Max Q/Episode', episode_avg_max_q)
        tf.compat.v1.summary.scalar('Duration/Episode', episode_duration)
        tf.compat.v1.summary.scalar('Average Loss/Episode', episode_avg_loss)

        summary_vars = [episode_total_reward, episode_avg_max_q,
                        episode_duration, episode_avg_loss]
        summary_placeholders = [tf.compat.v1.placeholder(tf.float32) for _ in
                                range(len(summary_vars))]
        update_ops = [summary_vars[i].assign(summary_placeholders[i]) for i in
                      range(len(summary_vars))]
        summary_op = tf.compat.v1.summary.merge_all()
        return summary_placeholders, update_ops, summary_op


# gray scaling
def pre_processing(observe):
    processed_observe = np.uint8(
        resize(rgb2gray(observe), (84, 84), mode='constant') * 255)
    return processed_observe


if __name__ == "__main__":
    env = loa_game.Env()

    if not os.path.exists('../save_model'):
        os.makedirs('../save_model')

    print(K.tensorflow_backend._get_available_gpus()) # for checking use of GPU
    agent = Agent()

    scores, episodes, global_step = [], [], 0

    for e in range(EPISODE_NUM):
        done = False
        dead = False

        step = 0
        score = 0
        observe = env.reset()

        for _ in range(random.randint(1, agent.no_op_steps)):
            observe, _, _, _ = env.step(1)

        state = pre_processing(observe)
        history = np.stack((state, state, state, state), axis=2)
        history = np.reshape([history], (1, 84, 84, 4))

        while not done:
            if agent.render:
                env.render()

            global_step += 1
            step += 1

            action = agent.get_action(history)

            # proceed one step
            observe, reward, done, info = env.step(action)

            # preprocess state for each time step
            next_state = pre_processing(observe)
            next_state = np.reshape([next_state], (1, 84, 84, 1))
            next_history = np.append(next_state, history[:, :, :, :3], axis=3)

            agent.avg_q_max += np.amax(
                agent.model.predict(np.float32(history / 255.))[0])

            reward = np.clip(reward, -1., 1.)

            # save sample <s, a, r, s'> to replay memory & training
            agent.append_sample(history, action, reward, next_history, dead)

            if len(agent.memory) >= agent.train_start:
                agent.train_model()

            # update target model at schedule intervals
            if global_step % agent.update_target_rate == 0:
                agent.update_target_model()

            score += reward

            if dead:
                dead = False
            else:
                history = next_history

            if done:
                # record training information per episode
                if global_step > agent.train_start:
                    stats = [score, agent.avg_q_max / float(step), step,
                             agent.avg_loss / float(step)]
                    for i in range(len(stats)):
                        agent.sess.run(agent.update_ops[i], feed_dict={
                            agent.summary_placeholders[i]: float(stats[i])
                        })
                    summary_str = agent.sess.run(agent.summary_op)
                    agent.summary_writer.add_summary(summary_str, e + 1)

                print(
                    "-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------")
                print("\t    episode:", e, " => score:", score, "  memory length:",
                      len(agent.memory), "  epsilon:", agent.epsilon,
                      "  global_step:", global_step, "  average_q:",
                      agent.avg_q_max / float(step), "  average loss:",
                      agent.avg_loss / float(step))
                print(
                    "-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------")

                agent.avg_q_max, agent.avg_loss = 0, 0

        # save model every 130 episodes
        if e % 130 == 0:
            agent.model.save_weights("../save_model/loa_trained.h5")

env.close()
