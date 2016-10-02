from rllab.misc.instrument import run_experiment_lite
from rllab import config
from rllab.misc.instrument import VariantGenerator, variant


USE_GPU = False#True#False  # True#False
USE_CIRRASCALE = True
MODE = "local_docker"

if USE_GPU:
    if USE_CIRRASCALE:
        config.DOCKER_IMAGE = "dementrock/rllab3-vizdoom-gpu-cuda80"
        config.KUBE_DEFAULT_NODE_SELECTOR = {
            "openai.org/machine-class": "cirrascale",
            "openai.org/gpu-type": "titanx-pascal",
        }
        if MODE == "local_docker":
            env = dict(OPENAI_N_GPUS="1", CUDA_VISIBLE_DEVICES="1")
        else:
            env = dict(OPENAI_N_GPUS="1")
    else:
        if MODE == "local_docker":
            config.DOCKER_IMAGE = "dementrock/rllab3-vizdoom-gpu-cuda80"
        else:
            config.DOCKER_IMAGE = "dementrock/rllab3-vizdoom-gpu"
        config.KUBE_DEFAULT_NODE_SELECTOR = {
            "aws/type": "g2.2xlarge",
        }
        config.KUBE_DEFAULT_RESOURCES = {
            "requests": {
                "cpu": 4 * 0.75,
            },
            "limits": {
                "cpu": 4 * 0.75,
            },
        }
        env = dict(CUDA_VISIBLE_DEVICES="1")
else:
    config.DOCKER_IMAGE = "dementrock/rllab3-vizdoom-gpu-cuda80"
    config.KUBE_DEFAULT_NODE_SELECTOR = {
        "aws/type": "c4.8xlarge",
    }
    config.KUBE_DEFAULT_RESOURCES = {
        "requests": {
            "cpu": 36 * 0.75,
            "memory": "50Gi",
        },
    }
    env = dict(CUDA_VISIBLE_DEVICES="")


def run_task(v):
    from rllab.policies.uniform_control_policy import UniformControlPolicy
    from sandbox.rocky.tf.envs.base import TfEnv
    from sandbox.rocky.tf.algos.nop import NOP
    from sandbox.rocky.neural_learner.envs.doom_goal_finding_maze_env import DoomGoalFindingMazeEnv
    from sandbox.rocky.neural_learner.envs.doom_default_wad_env import DoomDefaultWadEnv
    from rllab.baselines.zero_baseline import ZeroBaseline
    from rllab import config
    import os

    env = TfEnv(
        DoomDefaultWadEnv(
            os.path.join(config.PROJECT_PATH, "sandbox/rocky/neural_learner/envs/wads/vizdoom_levels/basic.wad")
        )
    )
    # env = TfEnv(DoomGoalFindingMazeEnv())
    policy = UniformControlPolicy(env.spec)
    baseline = ZeroBaseline(env.spec)

    algo = NOP(
        env=env,
        policy=policy,
        baseline=baseline,
        batch_size=1000,
        max_path_length=10,
        sampler_args=dict(n_envs=10),
    )
    algo.train()


run_experiment_lite(
    run_task,
    exp_prefix="doom_maze_4",
    mode=MODE,
    n_parallel=0,
    seed=11,#v["seed"],
    use_gpu=USE_GPU,
    use_cloudpickle=True,
    # variant=v,
    snapshot_mode="last",
    env=env,
    terminate_machine=True,
    sync_all_data_node_to_s3=False,
)
sys.exit()
