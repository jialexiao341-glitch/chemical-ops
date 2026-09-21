import { BasicContent } from "#src/components/basic-content";
import { FormAvatarItem } from "#src/components/basic-form";
import { useUserStore } from "#src/store/user";

import {
	ProForm,
	ProFormText,
	ProFormTextArea,
} from "@ant-design/pro-components";
import { Form } from "antd";

export default function Profile() {
	const currentUser = useUserStore(state => state);
	const getAvatarURL = () => {
		if (currentUser) {
			if (currentUser.avatar) {
				return currentUser.avatar;
			}
			const url = "https://avatar.vercel.sh/blur.svg?text=2";
			return url;
		}
		return "";
	};

	const handleFinish = async () => {
		window.$message?.success("更新基本信息成功");
	};

	return (
		<BasicContent className="max-w-md ml-10">
			<h3>我的资料</h3>
			<ProForm
				layout="vertical"
				onFinish={handleFinish}
				initialValues={{
					avatar: getAvatarURL(),
					username: currentUser.username,
					email: currentUser.email,
					phoneNumber: currentUser.phoneNumber,
					description: currentUser.description,
				}}
				requiredMark
			>
				<Form.Item
					name="avatar"
					label="头像"
					rules={[
						{
							required: true,
							message: "请输入您的昵称!",
						},
					]}
				>
					<FormAvatarItem />
				</Form.Item>
				<ProFormText
					name="username"
					label="用户名"
					rules={[
						{
							required: true,
							message: "请输入您的用户名!",
						},
					]}
				/>
				<ProFormText
					name="email"
					label="邮箱"
					rules={[
						{
							required: true,
							message: "请输入您的邮箱!",
						},
					]}
				/>
				<ProFormText
					name="phoneNumber"
					label="联系电话"
					fieldProps={{ type: "tel", allowClear: true }}
					rules={[
						{
							required: true,
							message: "请输入您的联系电话!",
						},
					]}
				/>
				<ProFormTextArea
					allowClear
					name="description"
					label="个人简介"
					placeholder="个人简介"
				/>
			</ProForm>
		</BasicContent>
	);
};
