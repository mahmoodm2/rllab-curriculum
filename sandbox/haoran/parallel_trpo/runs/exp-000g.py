"""
Other testing
1. timer
"""
import lasagne
from sandbox.haoran.parallel_trpo.trpo import ParallelTRPO
from sandbox.adam.parallel.first_order_optimizer import ParallelFirstOrderOptimizer
from rllab.optimizers.first_order_optimizer import FirstOrderOptimizer
from rllab.optimizers.conjugate_gradient_optimizer import ConjugateGradientOptimizer
from sandbox.haoran.parallel_trpo.conjugate_gradient_optimizer import ParallelConjugateGradientOptimizer
from sandbox.adam.parallel.parallel_nn_feature_linear_baseline import ParallelNNFeatureLinearBaseline
from sandbox.adam.parallel.linear_feature_baseline import ParallelLinearFeatureBaseline
from sandbox.adam.parallel.gaussian_conv_baseline import ParallelGaussianConvBaseline
from sandbox.adam.parallel.gaussian_conv_baseline import GaussianConvBaseline
from sandbox.adam.modified_sampler.batch_sampler import BatchSampler
from sandbox.haoran.myscripts.myutilities import get_time_stamp
from sandbox.haoran.ec2_info import instance_info, subnet_info
from rllab.baselines.linear_feature_baseline import LinearFeatureBaseline
from rllab.algos.trpo import TRPO
from rllab.policies.gaussian_mlp_policy import GaussianMLPPolicy
from rllab.envs.normalized_env import normalize
from rllab.envs.box2d.cartpole_env import CartpoleEnv
from rllab.envs.box2d.double_pendulum_env import DoublePendulumEnv
from rllab.envs.mujoco.hopper_env import HopperEnv
from rllab.envs.mujoco.walker2d_env import Walker2DEnv
from rllab.envs.mujoco.swimmer_env import SwimmerEnv
from rllab.envs.mujoco.ant_env import AntEnv
from rllab.envs.mujoco.half_cheetah_env import HalfCheetahEnv
from rllab.envs.mujoco.simple_humanoid_env import SimpleHumanoidEnv

from rllab import config
from rllab.misc.instrument import stub, run_experiment_lite
import sys,os
import copy

stub(globals())

from rllab.misc.instrument import VariantGenerator, variant

exp_prefix = "parallel-trpo/" + os.path.basename(__file__).split('.')[0] # exp_xxx

mode = "local_test"
ec2_instance = "c4.8xlarge"
subnet = "us-west-1c"

n_parallel = 4
snapshot_mode = "last"
store_paths = False
plot = False
use_gpu = False # should change conv_type and ~/.theanorc
sync_s3_pkl = True


# params ---------------------------------------
step_size = 0.01
batch_size = 1000
max_path_length = 500
discount = 0.99
n_itr = 1000


if sys.platform == "darwin":
    set_cpu_affinity = False
    cpu_assignments = None
    serial_compile = False
else:
    set_cpu_affinity = True
    cpu_assignments = None
    serial_compile = True

class VG(VariantGenerator):
    @variant
    def seed(self):
        return [0,100,200]
    @variant
    def env(self):
        return ["hopper","walker"]
    @variant
    def use_parallel(self):
        return [True]
    @variant
    def cg_iters(self):
        return [10]
    @variant
    def baseline_type_opt(self):
        return [
            # ["nn_feature_linear",""],
            ["conv","cg"],
            ["conv","sgd"],
            ["linear",""],
        ]
variants = VG().variants()

print("#Experiments: %d" % len(variants))
for v in variants:
    baseline_type, baseline_optimizer = v["baseline_type_opt"]
    policy_opt_args = dict(
        cg_iters=v["cg_iters"],
        subsample_factor=0.2,
        name="pi_opt"
    ) # worth tuning to see the speed up by parallelism

    env = v["env"]
    exp_name = "{time}_{env}".format(
        time=get_time_stamp(),
        env=env,
    )
    if ("ec2" in mode) and (len(exp_name) > 64):
        print("Should not use experiment name with length %d > 64.\nThe experiment name is %s.\n Exit now."%(len(exp_name),exp_name))
        sys.exit(1)

    if "local_docker" in mode:
        actual_mode = "local_docker"
    elif "local" in mode:
        actual_mode = "local"
    elif "ec2" in mode:
        actual_mode = "ec2"
        # configure instance
        info = instance_info[ec2_instance]
        config.AWS_INSTANCE_TYPE = ec2_instance
        config.AWS_SPOT_PRICE = str(info["price"])
        n_parallel = int(info["vCPU"] /2)

        # choose subnet
        config.AWS_NETWORK_INTERFACES = [
            dict(
                SubnetId=subnet_info[subnet]["SubnetID"],
                Groups=subnet_info[subnet]["Groups"],
                DeviceIndex=0,
                AssociatePublicIpAddress=True,
            )
        ]
    elif "kube" in mode:
        actual_mode = "lab_kube"
        info = instance_info[ec2_instance]
        n_parallel = int(info["vCPU"] /2)

        config.KUBE_DEFAULT_RESOURCES = {
            "requests": {
                "cpu": n_parallel
            }
        }
        config.KUBE_DEFAULT_NODE_SELECTOR = {
            "aws/type": ec2_instance
        }
        exp_prefix = exp_prefix.replace('/','-') # otherwise kube rejects
    else:
        raise NotImplementedError

    if env == "swimmer":
        env = normalize(SwimmerEnv())
    elif env == "hopper":
        env = normalize(HopperEnv())
    elif env == "walker":
        env = normalize(Walker2DEnv())
    elif env == "halfcheetah":
        env = normalize(HalfCheetahEnv())
    elif env == "ant":
        env = normalize(AntEnv())
    elif env == "humanoid":
        env = normalize(SimpleHumanoidEnv())
    elif env == "cartpole":
        env = normalize(CartpoleEnv())
    elif env == "double_pendulum":
        env = normalize(DoublePendulumEnv())
    else:
        raise NotImplementedError

    policy = GaussianMLPPolicy(
        env_spec=env.spec,
        hidden_sizes=(32, 32)
    )
    #----------------------------
    baseline_regressor_args = dict(
        hidden_sizes=(32,32),
        conv_filters=[],
        conv_filter_sizes=[],
        conv_strides=[],
        conv_pads=[],
        batchsize=batch_size,
        normalize_inputs=True,
        normalize_outputs=True,
    )
    if baseline_optimizer == "sgd":
        baseline_regressor_args["use_trust_region"] = False
    elif baseline_optimizer == "cg":
        baseline_regressor_args["use_trust_region"] = True
        baseline_regressor_args["step_size"] = 0.01

    if v["use_parallel"]:
        if baseline_type == "linear":
            baseline = ParallelLinearFeatureBaseline(env_spec=env.spec)
        elif baseline_type == "nn_feature_linear":
            baseline = ParallelNNFeatureLinearBaseline(
                env_spec=env.spec,
                policy=policy,
                nn_feature_power=2,
                t_power=3,
            )
        elif baseline_type == "conv":
            if baseline_optimizer == "sgd":
                optimizer = ParallelFirstOrderOptimizer(
                    learning_rate=1e-3,
                    name="vf_opt",
                    max_epochs=10,
                    verbose=False,
                    batch_size=None,
                )
            elif baseline_optimizer == "cg":
                optimizer = ParallelConjugateGradientOptimizer(
                    subsample_factor=0.2,
                    cg_iters=10,
                    name="vf_opt"
                )
            else:
                raise NotImplementedError
            baseline_regressor_args["optimizer"] = optimizer
            baseline = ParallelGaussianConvBaseline(
                env_spec=env.spec,
                regressor_args=baseline_regressor_args,
            )
        else:
            raise NotImplementedError

        algo = ParallelTRPO(
            env=env,
            policy=policy,
            baseline=baseline,
            batch_size=batch_size,
            max_path_length=max_path_length,
            discount=discount,
            n_itr=n_itr,
            plot=plot,
            step_size=step_size,
            store_paths=store_paths,
            n_parallel=n_parallel,
            optimizer_args=policy_opt_args,
            set_cpu_affinity=set_cpu_affinity,
            cpu_assignments=cpu_assignments,
            serial_compile=serial_compile,
        )
    else:
        if baseline_type == "linear":
            baseline = LinearFeatureBaseline(env_spec=env.spec)
        elif baseline_type == "conv":
            if baseline_optimizer == "sgd":
                optimizer = FirstOrderOptimizer(
                    update_method=lasagne.updates.sgd,
                    learning_rate=1e-3,
                    max_epochs=10,
                    batch_size=None,
                    verbose=False,
                )
            elif baseline_optimizer == "cg":
                optimizer = ConjugateGradientOptimizer(
                    subsample_factor=0.2,
                    cg_iters=10,
                    name="vf_opt"
                )
            baseline_regressor_args["optimizer"] = optimizer
            baseline = GaussianConvBaseline(
                env_spec=env.spec,
                regressor_args=baseline_regressor_args,
            )
        else:
            raise NotImplementedError

        algo = TRPO(
            env=env,
            policy=policy,
            baseline=baseline,
            batch_size=batch_size,
            max_path_length=max_path_length,
            discount=discount,
            n_itr=n_itr,
            plot=plot,
            step_size=step_size,
            store_paths=store_paths,
            optimizer_args=policy_opt_args,
            sampler_cls=BatchSampler # ensure fair comparison
        )


    # run --------------------------------------------------

    if v["use_parallel"]:
        run_experiment_lite(
            algo.train(),
            exp_prefix=exp_prefix,
            exp_name=exp_name,
            seed=v["seed"],
            snapshot_mode=snapshot_mode,
            mode=actual_mode,
            variant=v,
            use_gpu=use_gpu,
            plot=plot,
            sync_s3_pkl=sync_s3_pkl,
            terminate_machine=("test" not in mode),
            sync_all_data_node_to_s3=True,
        )
    else:
        run_experiment_lite(
            algo.train(),
            exp_prefix=exp_prefix,
            exp_name=exp_name,
            seed=v["seed"],
            snapshot_mode=snapshot_mode,
            mode=actual_mode,
            variant=v,
            use_gpu=use_gpu,
            plot=plot,
            sync_s3_pkl=sync_s3_pkl,
            terminate_machine=("test" not in mode),
            n_parallel=n_parallel,
            sync_all_data_node_to_s3=True,
        )



    if "test" in mode:
        sys.exit(0)

if ("local" not in mode) and ("test" not in mode):
    os.system("chmod 444 %s"%(__file__))
